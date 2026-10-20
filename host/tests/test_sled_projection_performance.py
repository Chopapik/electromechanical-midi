"""Projection acceleration must preserve the original discrete trajectory."""
import dataclasses
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playback.hardware_profiles import HardwareDeviceState,HardwareRegistry,advance_sled,braking_distance


def reference(state,profile,target,seconds):
    """Original 5 ms discrete projection, intentionally unoptimized."""
    import math
    travel=profile.get('travelSteps');a=profile.get('accelerationLimit')
    continuous=profile.get('continuousRotation')
    if (travel is None and not continuous) or a is None:return
    if state.position is None:state.position=0.
    state.position_confidence='LOW';state.physical_state_confidence='LOW'
    count=max(1,math.ceil(seconds/.005));dt=seconds/count
    for _ in range(count):
        v=state.current_step_rate;direction=state.direction
        if not continuous:
            remaining=travel-state.position if v>=0 else state.position
            if remaining<=braking_distance(v,a)+1:direction=-1 if v>=0 else 1
        requested=abs(target)*direction;dv=max(-a*dt,min(a*dt,requested-v));new=v+dv
        position=state.position+(v+new)*.5*dt
        state.position=position if continuous else max(0.,min(travel,position))
        if (v>=0 and new<0) or (v<0 and new>=0):state.travel_reversals+=1
        state.current_step_rate=new;state.direction=direction;state.target_step_rate=requested
    state.current_frequency=abs(state.current_step_rate)*profile.get('pitchRatio')


class SledProjectionPerformanceTests(unittest.TestCase):
    def test_exact_projection_including_steady_speed_ramp_and_reverse(self):
        profile=HardwareRegistry().effective('DVD_SLED','sled:1')
        for direction in (1,-1):
            for speed in (0.,220.,-330.,880.):
                for duration in (.003,.01,.137,.5,7.3):
                    with self.subTest(direction=direction,speed=speed,duration=duration):
                        a=HardwareDeviceState(position=.123,current_step_rate=speed,direction=direction)
                        b=dataclasses.replace(a)
                        for target in (220.,880.,440.,440.,100.):
                            reference(a,profile,target,duration);advance_sled(b,profile,target,duration)
                            self.assertEqual(dataclasses.asdict(a),dataclasses.asdict(b))

    def test_bounded_travel_projection_and_reversals_are_unchanged(self):
        profile=HardwareRegistry().effective('DVD_SLED','sled:1')
        q=dict(profile.quantities)
        q['continuousRotation']=dataclasses.replace(q['continuousRotation'],value=False)
        profile=dataclasses.replace(profile,quantities=q)
        a=HardwareDeviceState(position=139.,current_step_rate=600.)
        b=dataclasses.replace(a)
        for _ in range(20):
            reference(a,profile,600,.5);advance_sled(b,profile,600,.5)
            self.assertEqual(dataclasses.asdict(a),dataclasses.asdict(b))
