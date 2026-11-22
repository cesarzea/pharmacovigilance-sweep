-- Deploy the review app as Streamlit in Snowflake (scripts/snow_app.sh uploads app.py first).
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

CREATE STAGE IF NOT EXISTS OPS.APP_STAGE COMMENT = 'Streamlit review app files';

CREATE OR REPLACE STREAMLIT REVIEW.PVSWEEP_REVIEW
  ROOT_LOCATION = '@PVSWEEP.OPS.APP_STAGE/review'
  MAIN_FILE = 'app.py'
  QUERY_WAREHOUSE = PVSWEEP_WH
  COMMENT = 'Pharmacovigilance Sweep review app';

-- Snowflake does not allow GRANT OWNERSHIP on a Streamlit object, so the app stays owned by
-- PVSWEEP_ADMIN (the deploying role) and runs with that role's rights. A dedicated owner role would
-- need the app created from a session using that role.
GRANT USAGE ON STREAMLIT REVIEW.PVSWEEP_REVIEW TO ROLE PVSWEEP_REVIEWER;
GRANT USAGE ON STREAMLIT REVIEW.PVSWEEP_REVIEW TO ROLE PVSWEEP_REVIEW_APP;
