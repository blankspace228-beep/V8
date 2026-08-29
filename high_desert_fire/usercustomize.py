# Python imports usercustomize automatically after sitecustomize.
# If DATABASE_URL is configured, switch all application modules to PostgreSQL
# before loading the higher-level business operations package.
import db_postgres
db_postgres.activate()
import business_ops
