Put your manual PSI downloads here, one folder per investigation, keeping the NASA
folder structure inside:

    raw/PSI-26/...   BASS
    raw/PSI-25/...   BASS-II
    raw/PSI-98/...   SAFFIRE-I
    raw/PSI-99/...   SAFFIRE-II
    raw/PSI-100/...  SAFFIRE-III

Every file is inventoried (size + SHA-256) in output/source_inventory.csv.
CSV/XLSX tables that look like run tables are read automatically; everything else
(sensor time series, PDFs, images) is listed as "not parsed". PDFs are never parsed:
copy those values into a curated table in data/runs/ instead.
