"""NiceGUI presentation layer.

Nothing in here builds SQL or talks to BigQuery. Pages call `casefinder.data`,
which is the only seam between the UI and the warehouse — spec section 4.2.
"""
