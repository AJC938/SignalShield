# SignalShield — Public Web Deployment Report

**Date:** 2026-10-28  
**Platform requested:** Streamlit Community Cloud, free tier  
**Application entry point:** `src/signalshield/streamlit_app.py`  
**Preferred subdomain:** `signalshield-lab.streamlit.app`

## Status

- **Prepared for deployment:** Complete.
- **Uploaded to GitHub:** Pending initial public repository creation and push.
- **Deployment initiated:** Not yet.
- **Deployment successful:** Not yet.
- **Public URL verified:** Not yet; no URL has been assigned.

The project directory was not previously a Git repository and had no configured remote. GitHub CLI authentication is available for account `AJC938`, and no repository named `SignalShield` exists under that account. A public repository is being prepared because the requested app is meant to be freely accessible. No app URL or deployment success is assumed.

## Changes for deployment

- `requirements.txt` now installs this `src/` project in editable mode and pins the scientific/runtime versions already exercised locally: NumPy 2.4.6, SciPy 1.17.1, Matplotlib 3.11.2, and Streamlit 1.66.1. Streamlit supplies the transitive web/UI dependencies.
- `pyproject.toml` declares bounded supported major versions and a Streamlit app extra compatible with the tested UI.
- `.gitignore` excludes the virtual environment, Python/test caches, Streamlit secrets, local audio smoke fixture, generated Performance Lab output, and install-check logs. The `results/` figures and validation evidence referenced by project documentation remain included.
- Removed developer-machine absolute paths from historical reports and retained validation JSON/logs. A repository-wide scan of the included text files found no personal absolute path, credential/token pattern, or Streamlit secrets file.
- The transmission interface now has a centered, larger SignalShield heading and an Input → Signal System → Output composition with three visible signal paths. Actual recovered text/audio appears in the Output panel; signal analysis is below the flow.
- Public Performance Lab runs are limited to 250,000 bits per run, four repetitions, and 1,000,000 total bit trials across selected sweep conditions. Existing CLI experiments retain their research configurations. Interactive text/audio limits and numeric widget ranges remain in place.
- The app provides downloads for experiment manifests/results. Cloud-generated output files are treated as temporary; the UI tells users to download results they want to keep.

No API keys, secrets, external APIs, paid services, or extra native packages are required. Streamlit Community Cloud executes the app from the repository root, supports requirements/configuration at the root, and permits an entry point in a subdirectory; this matches the repository layout. Python 3.11 is selectable in the Community Cloud deployment settings.

## Validation performed

- `python -m compileall -q src/signalshield` — passed.
- `python -m pytest -q` — **93 passed in 9.01s**. Includes the existing M1–M6 test suite, Streamlit AppTest, WAV limits/normalization, framing/CRC/FEC, receiver comparisons, and the public experiment workload-budget check.
- `python -m pip install --dry-run -r requirements.txt` — passed in the current Python 3.11 environment; editable project metadata and all pinned direct dependencies resolved.
- Fresh-environment installation and import smoke check — **in progress**.
- Local Streamlit root and health endpoint on port 8522 — HTTP 200 and `ok`.
- Browser smoke run after the UI redesign — transmitted “SignalShield demo”; the output panel displayed the recovered text, exact-match/CRC success, and analysis displayed coded-bit BER 0 with zero errors.
- Earlier M6 browser validation covered WAV upload, paired baseline/notch receiver diagnostics, and the Performance Lab runner. Existing automated tests continue covering those paths.
- Streamlit Community Cloud documentation confirms the deployment fields, entry point handling, Python version selection, and public/private behavior. A public repository results in a public app by default; public viewing must still be verified after deployment.

## Repository and app URLs

- GitHub repository: pending creation; add the actual URL after successful push.
- Streamlit Community Cloud URL: pending deployment; add only after Community Cloud assigns it and the public URL responds successfully.
- The preferred subdomain will be requested during app creation. Its availability cannot be truthfully confirmed before the Community Cloud workflow assigns it.

## Remaining deployment workflow

1. Initialize the local `main` branch, commit the reviewed files, create the public `AJC938/SignalShield` repository, and push the branch.
2. In Streamlit Community Cloud, choose that repository and `main`, set the file path to `src/signalshield/streamlit_app.py`, and select Python 3.11.
3. Request `signalshield-lab` as the app subdomain if available and deploy on the free Community Cloud tier.
4. Inspect build logs and correct any cloud-only startup issues.
5. Confirm sharing is public, open the assigned HTTPS URL in a logged-out/public context, and verify the three tabs plus a text transmission. Verify audio upload and Performance Lab after deployment where available.
6. Update the README and this report with the real repository URL, assigned app URL, platform state, and public verification results. Add the Streamlit badge only after the URL is confirmed.

## Future updates

Push code changes to the deployed branch to trigger a Community Cloud rebuild. Keep runtime dependencies in `requirements.txt` and `.streamlit/config.toml` at the repository root. Review deployment logs if a dependency change causes build failure. Download any generated experiment data before the cloud app sleeps or restarts; its writable filesystem is temporary and is not a durable datastore.

## Known limits

- The Community Cloud deployment and public URL are not verified yet.
- Free Community Cloud is shared hosting. Availability, sleep/wake behavior, CPU/memory, and package-building limits are controlled by Streamlit and may change. Public input and compute limits are enforced in this UI but do not replace the platform's own resource limits.
- The simulator is educational discrete-time DSP, not an RF/security product. It has no user accounts, permanent experiment storage, or server-side secret requirement.

## References

- [Streamlit Community Cloud deployment workflow](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Community Cloud file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- [Community Cloud dependencies and Python versions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)
- [Sharing and public app visibility](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app)
