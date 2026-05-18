# Inkline

Simple notes, sharper tools.

## Run locally

```bash
python -m inkline.main
```

## Compile a desktop executable

Install build dependency:

```bash
python -m pip install pyinstaller
```

Build app bundle:

```bash
python tools/build_app.py
```

Build single-file executable:

```bash
python tools/build_app.py --onefile
```

Output is written to `dist/`.
