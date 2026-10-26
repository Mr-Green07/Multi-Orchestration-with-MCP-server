# Project report build

`Multi_Orchestration_MCP_Project_Report.pdf` is generated, not hand-written, so that
the numbers in Chapter 4 are the numbers the harnesses actually produced.

## Regenerate everything

```bash
python report/benchmark.py      # writes report/bench_results.json
python report/validation.py     # writes report/validation_results.json
python report/build_report.py   # writes the PDF (three passes, resolves page numbers)
```

Requires `reportlab`, `pymupdf` (only for previewing), `psutil` and `pydantic`.

## What is measured and what is characterised

| Source | Where it appears |
| --- | --- |
| `bench_results.json` | Table 4.3, Figure 4.1, Appendix-3 |
| `validation_results.json` | Table 4.6, Figure 4.5 |
| Characterisation run (model timings, soak test) | Tables 4.4, 4.5, 4.7 and Figures 4.2–4.7 |

The first two are reproducible on any machine by running the two harnesses. The third
was recorded on the reference laptop described in Table 4.1 and is labelled as a
characterisation in the report; re-running it requires the GGUF model and the Windows
hardware layer.

## Layout

| File | Purpose |
| --- | --- |
| `pdf_kit.py` | Typography, page numbering, captions, contents/figures/tables registers |
| `diagrams.py` | Every figure, drawn as vector graphics (no raster images) |
| `build_report.py` | Report content and the multi-pass build |
| `benchmark.py` / `validation.py` | The two measurement harnesses |
