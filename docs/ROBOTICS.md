# Robotics

The safety architecture is SPARKLE → Robot Gateway → ROS2 → independent Safety Controller → robot/simulation. Software gates reject direct motor/PWM/joint-voltage commands, require approval for motion, and check an independent emergency-stop callback before action. Physical robotics remains externally blocked until real hardware/sensors and an independent physical e-stop are genuinely connected and accepted.

Verified device/robot execution requires an independent adapter/verifier reread. Typed device contracts deny arbitrary GPIO and undeclared capabilities; robot control continues to deny direct motor/PWM/joint-voltage commands and checks the independent e-stop before every command.

## Generalized perception boundary

Gen-2 now normalizes perception through `PerceptionObservation` and `PerceptionService`. The contract carries observation/device/robot identity, sensor type, timestamp, reference frame, observation type, bounded data, confidence, source metadata, provenance, and a separate verification flag. Supported sensor categories are `camera`, `lidar`, `depth`, `imu`, `odometry`, `gps`, `joint_state`, `pose`, `battery`, and `proximity`. A declared sensor capability is distinct from a connected source and from live verification.

The current live local adapter is simulation-only: `ROS2PosePerceptionAdapter` rereads `/turtle1/pose` through the existing ROS2 gateway and emits the same normalized contract future physical providers must use. Observations are persisted by deterministic content identity and fused only within one registered robot identity. Compatible fresh pose/battery/etc. observations can form current robot state; conflicting fresh observations from different sources produce `CONFLICT` and do not silently overwrite world state. Confidence is evidence metadata, not a truth or authorization signal.

Freshness is evaluated from the original observation timestamp on every read. The default perception boundary treats observations as fresh for 10 seconds, stale afterwards, and expired after 120 seconds. Persisting or restarting never refreshes an observation. Perception-derived world nodes are excluded from normal PersonalAgent context once they age beyond the fresh perception window. A PersonalAgent-mediated ROS2 move requires a fresh perception state before the existing human-approval, independent safety-controller, e-stop, bounded-motion, and post-action ROS2 verification gates.

Camera/depth semantic understanding uses the separate NVIDIA Omni `perception` + `multimodal` route when a bounded image source is actually available. Model capability does not imply a physical sensor: physical camera/LiDAR/robot perception remains externally blocked until a real registered sensor provides observations. Recorded/simulated inputs are labeled simulation/recorded evidence and never promoted to physical observation.

## Simulation acceptance

On the authoritative workstation, an actual offscreen turtlesim node and the repository's real `/sparkle_safety_controller` node were started for acceptance. Gen-2 observed a live pose, persisted normalized perception/world provenance, waited for human approval, executed a bounded relative move through the safety controller, independently reread the ROS2 pose, and captured a fresh post-move perception observation. This is `SIMULATION_LIVE_VERIFIED`; it is not evidence of physical robot or physical sensor support.

## Robotics Engineer workspace finalization

RoboticsEngineerMode is a bounded read-oriented projection over the existing RobotSafetyGateway, WorldModel, perception, experiment, document, research, and engineering services. It introduces no raw ROS2 or shell path. Diagnostic findings are derived from actual gateway/world/perception evidence. Motion remains separate: verified motion requires explicit approval and RobotSafetyGateway.execute_verified; only independently verified post-action state is written back to the WorldModel. Physical robotics remains externally blocked when no real robot plus independent safety/e-stop environment is attached.
