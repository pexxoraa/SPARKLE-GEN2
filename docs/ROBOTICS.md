# Robotics

The safety architecture is SPARKLE → Robot Gateway → ROS2 → independent Safety Controller → robot. Software gates reject direct motor/PWM/joint-voltage commands, require approval for motion, and check an independent emergency-stop callback before action. Live robotics remains externally blocked until a ROS2 robot gateway, real target and independent e-stop are available.

Verified device/robot execution requires an independent adapter/verifier reread. Typed device contracts deny arbitrary GPIO and undeclared capabilities; robot control continues to deny direct motor/PWM/joint-voltage commands and checks the independent e-stop before every command.
