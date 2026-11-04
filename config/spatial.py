"""Shared PostGIS boundary behavior for proximity bands and analytics."""

# Floating point rounding at ST_Project/ST_DWithin threshold boundaries.
EXPOSURE_BOUNDARY_TOLERANCE_METERS = 0.001
