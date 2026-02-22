from pymavlink import mavutil

def connect_udpin(port: int, timeout_s: float = 30.0, dialect: str = "common"):
    """
    Connect to a MAVLink stream being sent to this machine on UDP <port>.
    Returns a pymavlink connection with heartbeat received.
    """
    m = mavutil.mavlink_connection(f"udpin:0.0.0.0:{port}", dialect=dialect)
    m.wait_heartbeat(timeout=timeout_s)
    return m
