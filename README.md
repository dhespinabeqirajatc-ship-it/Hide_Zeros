# Workiva Zero-Row Hider — OpenShift CronJob

This project converts the working Google Colab script into an OpenShift batch job.

## What changed

The Workiva business logic is preserved. The OpenShift version changes only the runtime model:

- Google Colab `userdata` secrets → OpenShift environment variables / Secret
- `while True` + `sleep(24 hours)` → OpenShift `CronJob`
- one container run performs one check and exits
- a Python exception exits non-zero so OpenShift records the Job as failed
- the default Workiva API remains `2026-01-01` and the EU endpoint remains `https://api.eu.wdesk.com`

The control behavior remains:

- control cell `TRUE` → do nothing and exit successfully
- control cell `FALSE` → process every configured spreadsheet
- all spreadsheets succeed → reset the control cell to `TRUE`
- processing fails → the process fails and the control cell remains unchanged

## Files

- `main.py` — Workiva worker
- `Dockerfile` — builds the worker container
- `requirements.txt` — Python dependency
- `buildconfig.yaml` — optional OpenShift GitHub → ImageStream build
- `cronjob.yaml` — daily scheduled execution
- `secret.example.yaml` — template only; do not commit real credentials
- `.gitignore` — excludes Python cache and `secret.yaml`

## 1. Create a new GitHub repository

Upload the files in this folder to a new repository, for example:

`workiva-zero-row-hider`

Do **not** put real Workiva credentials into GitHub.

## 2. Log in to OpenShift and select your project

```bash
oc project YOUR_PROJECT
```

Check it:

```bash
oc project
```

## 3. Create the Workiva Secret

The recommended method is to create it from the CLI so credentials never need to be stored in GitHub:

```bash
oc create secret generic workiva-zero-row-secrets \
  --from-literal=WORKIVA_CLIENT_ID='YOUR_CLIENT_ID' \
  --from-literal=WORKIVA_CLIENT_SECRET='YOUR_CLIENT_SECRET' \
  --from-literal=WORKIVA_DOCUMENT_IDS='id1,id2,id3' \
  --from-literal=WORKIVA_CONTROL_SPREADSHEET_ID='YOUR_CONTROL_SPREADSHEET_ID' \
  --from-literal=WORKIVA_CONTROL_SHEET_ID='YOUR_CONTROL_SHEET_ID'
```

Verify the Secret exists without printing its secret values:

```bash
oc get secret workiva-zero-row-secrets
```

## 4. Configure the GitHub build

Edit `buildconfig.yaml` and replace:

```text
https://github.com/YOUR_GITHUB_USER/YOUR_REPOSITORY.git
```

with your repository URL.

Then create the build resources:

```bash
oc apply -f buildconfig.yaml
```

Start the first build:

```bash
oc start-build workiva-zero-row-hider --follow
```

Check the ImageStream:

```bash
oc get imagestream workiva-zero-row-hider
```

## 5. Configure the CronJob image

Edit `cronjob.yaml` and replace:

```text
YOUR_PROJECT
```

with your real OpenShift project/namespace.

For example:

```text
image-registry.openshift-image-registry.svc:5000/deppytest-dev/workiva-zero-row-hider:latest
```

## 6. Choose the schedule

The supplied file contains:

```yaml
schedule: "0 0 * * *"
```

That means **once per day at 00:00 UTC**.

Examples:

```text
0 6 * * *     every day at 06:00 UTC
0 12 * * 1-5  weekdays at 12:00 UTC
```

Change the schedule before applying it if required.

## 7. Create the CronJob

```bash
oc apply -f cronjob.yaml
```

Check it:

```bash
oc get cronjob
```

## 8. Test immediately — do not wait until tomorrow

Create a one-off Job from the CronJob:

```bash
oc create job --from=cronjob/workiva-zero-row-hider workiva-zero-row-test
```

Watch the pod:

```bash
oc get pods -w
```

Then read the logs:

```bash
oc logs job/workiva-zero-row-test
```

If you need to run another test, delete the previous test Job first:

```bash
oc delete job workiva-zero-row-test
```

Then create it again.

## 9. Check scheduled runs

```bash
oc get jobs
```

Logs for a specific Job:

```bash
oc logs job/JOB_NAME
```

Describe a failed Job:

```bash
oc describe job JOB_NAME
```

## 10. Update the Python code later

Push the change to GitHub:

```bash
git pull
git add .
git commit -m "Update Workiva zero-row worker"
git push
```

Then build the new image:

```bash
oc start-build workiva-zero-row-hider --follow
```

Because the CronJob uses `imagePullPolicy: Always`, future Job pods will pull the current `latest` image.

## Important security note

Never commit a real `secret.yaml` containing the Workiva client secret. `secret.example.yaml` contains placeholders only.

## Optional configuration

The worker also accepts:

- `WORKIVA_CONTROL_CELL` — defaults to `B2`
- `WORKIVA_API_VERSION` — defaults to `2026-01-01`
- `WORKIVA_BASE_URL` — defaults to `https://api.eu.wdesk.com`

These are already set in `cronjob.yaml` and can be changed there.
