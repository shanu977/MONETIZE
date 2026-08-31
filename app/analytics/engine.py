"""Analytics Engine — Phase 3: Detection & Tracking Analytics.

Single authoritative customer tracking state, zone entry/exit, dwell, occupancy,
counting, lost-track, transitions, boundary hysteresis.

Uses:
  - YOLO + ByteTrack via TrackingResult (already filtered to person)
  - ZoneTrackingIntegrator for camera→map→zone (bottom-center, existing calibration)
  - ZoneEngine for polygon checks (via integrator)

Performance: zones and homography loaded once, reused. No disk reads per frame.
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import PROJECT_ROOT
from app.models.tracking_data import TrackedCustomer, TrackingResult
from app.analytics.models import CustomerTrackState, ZoneStatistics, AnalyticsSnapshot, ZoneEvent
from app.phase2.integration import ZoneTrackingIntegrator

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────
# Documented reasoning:
# - LOST_TRACK_GRACE_SECONDS: How long to keep a track alive after disappearance.
#   At 30 FPS, 2.0s ≈ 60 frames; at 6 inference FPS, 2.0s ≈ 12 inference frames.
#   We use time-based grace (seconds) primarily, plus missed_frames as fallback.
# - ZONE_STATE_CONFIRMATION_FRAMES: How many consecutive frames a new zone must be
#   observed before confirming transition. Prevents boundary jitter (inside/outside flicker).
#   3 frames at 6 FPS ≈ 0.5s, responsive but stable. At 30 FPS, 3 frames ≈ 0.1s.
DEFAULT_LOST_TRACK_GRACE_SECONDS = 2.0
DEFAULT_LOST_TRACK_MAX_MISSED_FRAMES = 30
DEFAULT_ZONE_CONFIRMATION_FRAMES = 3


class AnalyticsEngine:
    """Central analytics state for Phase 3.

    Usage:
        engine = AnalyticsEngine(map_id="d6f8bd3b", camera_id="default_camera")
        events = engine.update(tracking_result, timestamp=time.time(), frame_number=frame_idx)
        snapshot = engine.get_snapshot()
    """

    def __init__(
        self,
        map_id: Optional[str] = None,
        camera_id: str = "default_camera",
        zones_dir: str | Path | None = None,
        maps_dir: str | Path | None = None,
        calibration_dir: str | Path | None = None,
        camera_resolution: Optional[tuple[int, int]] = None,
        lost_track_grace_seconds: float = DEFAULT_LOST_TRACK_GRACE_SECONDS,
        lost_track_max_missed_frames: int = DEFAULT_LOST_TRACK_MAX_MISSED_FRAMES,
        zone_confirmation_frames: int = DEFAULT_ZONE_CONFIRMATION_FRAMES,
    ):
        self.map_id = map_id
        self.camera_id = camera_id
        self.lost_track_grace_seconds = lost_track_grace_seconds
        self.lost_track_max_missed_frames = lost_track_max_missed_frames
        self.zone_confirmation_frames = zone_confirmation_frames

        # Use integrator for camera→map→zone (cached, not per frame)
        # If map_id is None, integrator will try selected map; if that fails, we still run without zones
        try:
            self.integrator = ZoneTrackingIntegrator(
                map_id=map_id,
                camera_id=camera_id,
                zones_dir=zones_dir,
                maps_dir=maps_dir,
                calibration_dir=calibration_dir,
                camera_resolution=camera_resolution,
            )
            self.map_id = self.integrator.map_id  # resolved
        except Exception as e:
            logger.warning(f"AnalyticsEngine: failed to init integrator: {e}")
            self.integrator = None
            if not self.map_id:
                self.map_id = map_id or "unknown"

        # State: track_id -> CustomerTrackState
        self.tracks: dict[int, CustomerTrackState] = {}
        # Unique session customers
        self.unique_customers: set[int] = set()
        # Zone statistics: zone_id -> ZoneStatistics
        self.zone_stats: dict[str, ZoneStatistics] = {}
        # Events history (for API)
        self.events: list[ZoneEvent] = []
        # For occupancy and dwell tracking
        self._init_zone_stats()

        # Frame tracking
        self.frame_number: int = 0
        self.last_update_time: float = time.time()

    def _init_zone_stats(self) -> None:
        if not self.integrator:
            return
        try:
            for z in self.integrator.zone_engine.zones:
                zid = z["zone_id"]
                if zid not in self.zone_stats:
                    self.zone_stats[zid] = ZoneStatistics(
                        zone_id=zid,
                        zone_name=z["name"],
                    )
        except Exception:
            pass

    def _ensure_zone_stat(self, zone_id: str, zone_name: str) -> ZoneStatistics:
        if zone_id not in self.zone_stats:
            self.zone_stats[zone_id] = ZoneStatistics(zone_id=zone_id, zone_name=zone_name)
        return self.zone_stats[zone_id]

    def _get_zone_for_customer(self, customer: TrackedCustomer) -> tuple[Optional[str], Optional[str], Optional[tuple[float, float]], Optional[tuple[float, float]]]:
        """Return (zone_id, zone_name, camera_pos, map_pos) for a customer."""
        if not self.integrator:
            # No integrator: no map/zone
            try:
                cam_pos = (float(customer.bottom_center[0]), float(customer.bottom_center[1]))
            except Exception:
                cam_pos = None
            return None, None, cam_pos, None
        try:
            result = self.integrator.process_tracked_customer(customer)
            return result.zone_id, result.zone_name, result.camera_position, result.map_position
        except Exception as e:
            logger.warning(f"Zone lookup failed for track {customer.track_id}: {e}")
            try:
                cam_pos = (float(customer.bottom_center[0]), float(customer.bottom_center[1]))
            except Exception:
                cam_pos = None
            return None, None, cam_pos, None

    def update(self, tracking_result: TrackingResult, timestamp: Optional[float] = None, frame_number: Optional[int] = None) -> list[ZoneEvent]:
        """Update analytics with new tracking result. Returns list of new events for this frame.

        Handles:
          - track creation/update via bottom-center + zone
          - entry/exit with hysteresis
          - dwell time
          - occupancy (via snapshot, not per frame event)
          - lost-track grace
          - transitions
        """
        now = timestamp if timestamp is not None else time.time()
        if frame_number is not None:
            self.frame_number = frame_number
        else:
            self.frame_number += 1
        self.last_update_time = now

        # Ensure zone stats exist for any new zones (if zones reloaded)
        self._init_zone_stats()

        current_track_ids = set()
        new_events: list[ZoneEvent] = []

        # Process each currently visible customer
        for customer in tracking_result.customers:
            tid = customer.track_id
            current_track_ids.add(tid)
            self.unique_customers.add(tid)

            zone_id, zone_name, cam_pos, map_pos = self._get_zone_for_customer(customer)

            # Get or create track state
            if tid not in self.tracks:
                # New track
                state = CustomerTrackState(
                    track_id=tid,
                    customer_id=customer.customer_id,
                    first_seen=now,
                    last_seen=now,
                    last_position=cam_pos,
                    last_map_position=map_pos,
                    current_zone_id=zone_id,
                    previous_zone_id=None,
                    entered_zone_at=now if zone_id else None,
                    is_currently_tracked=True,
                    missed_frames=0,
                    last_seen_frame=self.frame_number,
                    last_bbox=customer.bbox.to_list(),
                )
                # For new track, if it starts inside a zone, that's an entry
                if zone_id:
                    state.entry_count = 1
                    stat = self._ensure_zone_stat(zone_id, zone_name or zone_id)
                    stat.total_entries += 1
                    # Active dwell will be computed in snapshot
                    new_events.append(ZoneEvent(
                        event_type="zone_entry",
                        track_id=tid,
                        customer_id=customer.customer_id,
                        zone_id=zone_id,
                        zone_name=zone_name,
                        from_zone_id=None,
                        from_zone_name=None,
                        timestamp=now,
                        map_id=self.map_id,
                        camera_position=cam_pos,
                        map_position=map_pos,
                    ))
                    logger.debug(f"[ZONE DEBUG] track_id={tid} zone=None -> {zone_id} event=ENTRY")
                else:
                    # Started outside
                    pass

                new_events.append(ZoneEvent(
                    event_type="track_started",
                    track_id=tid,
                    customer_id=customer.customer_id,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    timestamp=now,
                    map_id=self.map_id,
                    camera_position=cam_pos,
                    map_position=map_pos,
                ))
                logger.debug(f"[TRACK DEBUG] track_id={tid} status=started")
                self.tracks[tid] = state

                # Also handle pending zone initialization
                state.pending_zone_id = zone_id
                state.pending_zone_frames = 1 if zone_id else 0
            else:
                # Existing track: update
                state = self.tracks[tid]
                state.previous_position = state.last_position
                state.last_position = cam_pos
                state.last_map_position = map_pos
                state.last_seen = now
                state.last_seen_frame = self.frame_number
                state.is_currently_tracked = True
                state.missed_frames = 0
                state.last_bbox = customer.bbox.to_list()
                # Reset pending if track reappeared after being lost
                # (missed_frames was >0, now zero)

                # ── Zone hysteresis ──
                # We don't immediately switch current_zone; we require stable pending zone
                if zone_id == state.current_zone_id:
                    # Same zone, reset pending
                    state.pending_zone_id = zone_id
                    state.pending_zone_frames = 0
                else:
                    # Different zone (including None)
                    if zone_id == state.pending_zone_id:
                        state.pending_zone_frames += 1
                    else:
                        state.pending_zone_id = zone_id
                        state.pending_zone_frames = 1

                    # Check if we should confirm transition
                    if state.pending_zone_frames >= self.zone_confirmation_frames:
                        # Confirm transition
                        old_zone = state.current_zone_id
                        old_name = self._zone_name_for_id(old_zone)
                        new_zone = zone_id
                        new_name = zone_name

                        # Only generate events if actually changing
                        if old_zone != new_zone:
                            # Handle exit from old zone
                            if old_zone is not None:
                                # Calculate dwell
                                dwell = 0.0
                                if state.entered_zone_at is not None:
                                    dwell = now - state.entered_zone_at
                                    # Update zone stats for old zone
                                    stat_old = self.zone_stats.get(old_zone)
                                    if stat_old:
                                        stat_old.total_exits += 1
                                        stat_old.total_dwell_seconds += max(0, dwell)
                                        if dwell > stat_old.maximum_dwell_seconds:
                                            stat_old.maximum_dwell_seconds = dwell
                                        stat_old.completed_visits += 1
                                        # Recalc average
                                        if stat_old.completed_visits > 0:
                                            stat_old.average_dwell_seconds = stat_old.total_dwell_seconds / stat_old.completed_visits
                                new_events.append(ZoneEvent(
                                    event_type="zone_exit",
                                    track_id=tid,
                                    customer_id=customer.customer_id,
                                    zone_id=old_zone,
                                    zone_name=old_name,
                                    from_zone_id=old_zone,
                                    from_zone_name=old_name,
                                    timestamp=now,
                                    map_id=self.map_id,
                                    dwell_seconds=dwell if old_zone else None,
                                    camera_position=cam_pos,
                                    map_position=map_pos,
                                ))
                                logger.debug(f"[ZONE DEBUG] track_id={tid} zone={old_zone} -> {new_zone} event=EXIT dwell={dwell:.1f}s")
                                # Also transition event if moving between zones
                                if new_zone is not None:
                                    new_events.append(ZoneEvent(
                                        event_type="zone_transition",
                                        track_id=tid,
                                        customer_id=customer.customer_id,
                                        zone_id=new_zone,
                                        zone_name=new_name,
                                        from_zone_id=old_zone,
                                        from_zone_name=old_name,
                                        timestamp=now,
                                        map_id=self.map_id,
                                        camera_position=cam_pos,
                                        map_position=map_pos,
                                    ))

                            # Handle entry to new zone
                            if new_zone is not None:
                                stat_new = self._ensure_zone_stat(new_zone, new_name or new_zone)
                                stat_new.total_entries += 1
                                new_events.append(ZoneEvent(
                                    event_type="zone_entry",
                                    track_id=tid,
                                    customer_id=customer.customer_id,
                                    zone_id=new_zone,
                                    zone_name=new_name,
                                    from_zone_id=old_zone,
                                    from_zone_name=old_name,
                                    timestamp=now,
                                    map_id=self.map_id,
                                    camera_position=cam_pos,
                                    map_position=map_pos,
                                ))
                                logger.debug(f"[ZONE DEBUG] track_id={tid} zone={old_zone} -> {new_zone} event=ENTRY")
                                state.entered_zone_at = now
                                state.entry_count += 1
                            else:
                                # Exiting to outside
                                state.entered_zone_at = None
                                state.exit_count += 1

                            # Update state
                            state.previous_zone_id = old_zone
                            state.current_zone_id = new_zone
                            # Reset pending
                            state.pending_zone_id = new_zone
                            state.pending_zone_frames = 0
                        else:
                            # No actual change, reset pending
                            state.pending_zone_id = new_zone
                            state.pending_zone_frames = 0
                # Update dwell for current zone
                state.update_dwell(now)

        # Handle lost tracks (not in current frame)
        for tid, state in list(self.tracks.items()):
            if tid not in current_track_ids and state.is_currently_tracked:
                state.missed_frames += 1
                # Check grace: time-based and frame-based
                time_since_seen = now - state.last_seen
                if (time_since_seen > self.lost_track_grace_seconds) or (state.missed_frames > self.lost_track_max_missed_frames):
                    # Still keep state as not currently tracked, but don't immediately finalize zone?
                    # We finalize zone presence after grace: generate exit if inside zone
                    if state.current_zone_id is not None:
                        dwell = 0.0
                        if state.entered_zone_at is not None:
                            dwell = now - state.entered_zone_at
                            stat = self.zone_stats.get(state.current_zone_id)
                            if stat:
                                stat.total_exits += 1
                                stat.total_dwell_seconds += max(0, dwell)
                                if dwell > stat.maximum_dwell_seconds:
                                    stat.maximum_dwell_seconds = dwell
                                stat.completed_visits += 1
                                if stat.completed_visits > 0:
                                    stat.average_dwell_seconds = stat.total_dwell_seconds / stat.completed_visits
                        new_events.append(ZoneEvent(
                            event_type="zone_exit",
                            track_id=tid,
                            customer_id=state.customer_id,
                            zone_id=state.current_zone_id,
                            zone_name=self._zone_name_for_id(state.current_zone_id),
                            from_zone_id=state.current_zone_id,
                            from_zone_name=self._zone_name_for_id(state.current_zone_id),
                            timestamp=now,
                            map_id=self.map_id,
                            dwell_seconds=dwell,
                            camera_position=state.last_position,
                            map_position=state.last_map_position,
                        ))
                        logger.debug(f"[ZONE DEBUG] track_id={tid} zone={state.current_zone_id} -> None event=EXIT (lost) dwell={dwell:.1f}s")
                        state.previous_zone_id = state.current_zone_id
                        state.current_zone_id = None
                        state.entered_zone_at = None
                        state.exit_count += 1

                    new_events.append(ZoneEvent(
                        event_type="track_lost",
                        track_id=tid,
                        customer_id=state.customer_id,
                        timestamp=now,
                        map_id=self.map_id,
                        camera_position=state.last_position,
                        map_position=state.last_map_position,
                    ))
                    logger.debug(f"[TRACK DEBUG] track_id={tid} missed_frames={state.missed_frames} status=lost")
                    state.is_currently_tracked = False
                else:
                    # Still within grace, keep alive, update dwell
                    state.update_dwell(now)
                    logger.debug(f"[TRACK DEBUG] track_id={tid} missed_frames={state.missed_frames} status=alive (grace)")
            elif tid not in current_track_ids and not state.is_currently_tracked:
                # Already lost, check if we should finalize (track_ended) after longer period
                # For now, after grace*2, mark as ended
                time_since_seen = now - state.last_seen
                if time_since_seen > self.lost_track_grace_seconds * 2 or state.missed_frames > self.lost_track_max_missed_frames * 2:
                    # Finalize
                    new_events.append(ZoneEvent(
                        event_type="track_ended",
                        track_id=tid,
                        customer_id=state.customer_id,
                        timestamp=now,
                        map_id=self.map_id,
                        camera_position=state.last_position,
                        map_position=state.last_map_position,
                    ))
                    logger.debug(f"[TRACK DEBUG] track_id={tid} status=ended")
                    # Keep in dict but mark as not tracked; or optionally remove? Keep for history.
                    # For occupancy, it already removed from zone, so fine.
                    pass

        # Update dwell for all active tracks
        for state in self.tracks.values():
            if state.is_currently_tracked:
                state.update_dwell(now)

        # Append events to history
        self.events.extend(new_events)
        # Keep only last 1000 events to avoid memory bloat
        if len(self.events) > 1000:
            self.events = self.events[-1000:]

        return new_events

    def _zone_name_for_id(self, zone_id: Optional[str]) -> Optional[str]:
        if not zone_id:
            return None
        stat = self.zone_stats.get(zone_id)
        if stat:
            return stat.zone_name
        # Try to get from integrator
        if self.integrator:
            try:
                for z in self.integrator.zone_engine.zones:
                    if z["zone_id"] == zone_id:
                        return z["name"]
            except Exception:
                pass
        return None

    def get_snapshot(self) -> AnalyticsSnapshot:
        """Return current analytics snapshot for API/dashboard."""
        now = time.time()
        active = [s for s in self.tracks.values() if s.is_currently_tracked]
        # Update zone occupancy based on current active tracks
        # Reset counts
        for stat in self.zone_stats.values():
            stat.current_occupancy = 0
            stat.active_dwell_times = []

        for state in active:
            if state.current_zone_id and state.current_zone_id in self.zone_stats:
                stat = self.zone_stats[state.current_zone_id]
                stat.current_occupancy += 1
                # Active dwell
                if state.entered_zone_at:
                    dwell = now - state.entered_zone_at
                    stat.active_dwell_times.append(dwell)

        total_occupancy = sum(s.current_occupancy for s in self.zone_stats.values())
        total_entries = sum(s.total_entries for s in self.zone_stats.values())
        total_exits = sum(s.total_exits for s in self.zone_stats.values())

        # Ensure zone stats have up-to-date average/max (already maintained)
        zone_stats_list = list(self.zone_stats.values())
        # Sort by zone_id for determinism
        zone_stats_list.sort(key=lambda z: z.zone_id)

        return AnalyticsSnapshot(
            timestamp=now,
            active_customers=len(active),
            total_unique_customers=len(self.unique_customers),
            total_entries=total_entries,
            total_exits=total_exits,
            zone_statistics=zone_stats_list,
            total_occupancy=total_occupancy,
            tracking_status="running" if active else "idle",
        )

    def get_events(self, limit: int = 100) -> list[ZoneEvent]:
        return self.events[-limit:]

    def reset(self) -> None:
        """Reset all state (for testing)."""
        self.tracks.clear()
        self.unique_customers.clear()
        self.events.clear()
        for stat in self.zone_stats.values():
            stat.current_occupancy = 0
            stat.total_entries = 0
            stat.total_exits = 0
            stat.total_dwell_seconds = 0.0
            stat.average_dwell_seconds = 0.0
            stat.maximum_dwell_seconds = 0.0
            stat.active_dwell_times = []
            stat.completed_visits = 0

    def __repr__(self) -> str:
        return f"AnalyticsEngine(map_id={self.map_id!r}, tracks={len(self.tracks)}, zones={len(self.zone_stats)})"
