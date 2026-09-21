# Streamlit Cloud connection

The dashboard connects directly to the existing remote DuckLake catalog and S3
files. It uses an in-memory DuckDB connection; `nera_oc.duckdb` is not required.

1. Push the application code, `requirements.txt`, and the connection changes in
   `newduck.py` to the repository used by Streamlit Cloud.
2. Open the Cloud app's settings and select **Secrets**.
3. Copy `.streamlit/secrets.toml.example` into the Secrets editor. Replace every
   placeholder with the corresponding values from your existing configuration:
   - `ducklake.postgres`: your `supabase_pg_secret` connection values.
   - `ducklake.s3`: your `my_secret` storage credentials and options. Match its
     endpoint, region, and URL style. The endpoint excludes `https://`.
   - `ducklake.catalog`: your `lakehouse` data path and metadata schema. Use the
     existing values exactly; do not create a new lake or change its storage path.
4. Save the secrets and reboot the app if necessary. The entry point is
   `streamlit_ntpay.py`.
5. Confirm that filters load and that a dashboard tab displays data. This checks
   access to both the catalog and the underlying files from Cloud.

The credentials must allow access from the Cloud host to both services. A
successful local connection alone does not verify Cloud network access.

For local testing of the same configuration, copy the example to
`.streamlit/secrets.toml` and fill it in. That file is ignored by Git. Do not paste
credentials into Python files or commit them. Without a `ducklake` secrets section,
the app continues to use the existing local DuckDB persistent secrets.

The app creates temporary secrets on each connection and attaches DuckLake in
read-only mode. Cloud configuration replaces the three named secrets only for
that connection; it does not overwrite the local persistent secret files.
