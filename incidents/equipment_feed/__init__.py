"""
External equipment-status data for ExpoPulse.

paris_open_data  - fetch and normalize the Paris Open Data lift/escalator feed
detection        - rule-based fault detection over normalized status records

Neither module imports Django, so both can be tested and reasoned about on
their own. Sending readings to ExpoPulse is done by the
``monitor_equipment_feed`` management command through the existing
``/api/equipment/readings/`` endpoint.
"""
