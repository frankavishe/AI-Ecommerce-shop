# Eval photos

The photo cases need real pictures. The repo doesn't ship them (licensing and size), so add them by hand
before scoring photo search.

- `catalog/<SKU>.jpg`: the shop's product photo for each SKU listed under `catalog_images` in
  `../photos.json`. `rag_eval --seed` attaches these to the seeded products and indexes them.
- `queries/<name>.jpg`: a *different* photo of the same product, as a shopper would take it (another
  angle, background or lighting). Each one is a case under `cases` in `../photos.json`, with its
  expected SKU.

Any JPEG/PNG works. Keep them under 2 MB, since they're downsized to 1024 px before embedding anyway.
`rag_eval` skips cases whose files are missing and says how many it skipped.

```bash
python manage.py rag_eval --seed --kind photo
python manage.py rag_eval --kind photo --min-photo 0.7
```
