#!/usr/bin/env Rscript
# Fetch real 2011 Census journey-to-work OD flows (car_driver) + MSOA zones
# for West Yorkshire via the `pct` package, for the cityseer OD-betweenness
# benchmark (scripts/bench_cityseer_od.py).
#
# IMPORTANT: geography = "msoa" must be passed explicitly to get_pct_zones().
# The default "lsoa" returns zone codes that do not match get_od() output at
# all (0 matched OD pairs) -- a real bug hit and documented in the sibling
# criticalissues project. Do not repeat it.
suppressMessages({
  library(pct)
  library(sf)
})

od <- pct::get_od(region = "west-yorkshire")
zones <- pct::get_pct_zones(region = "west-yorkshire", geography = "msoa")

cat("OD rows:", nrow(od), "\n")
cat("Zones:", nrow(zones), "\n")
cat("OD geo_code1 sample:", head(od$geo_code1, 3), "\n")
cat("Zones geo_code sample:", head(zones$geo_code, 3), "\n")

matched <- sum(od$geo_code1 %in% zones$geo_code & od$geo_code2 %in% zones$geo_code)
cat("Matched OD pairs (both zones present):", matched, "/", nrow(od), "\n")
if (matched == 0) {
  stop("0 matched OD pairs between get_od() and get_pct_zones() -- geography mismatch")
}

keep_cols <- intersect(c("geo_code1", "geo_code2", "all", "bicycle", "foot",
                          "car_driver", "car_passenger", "motorbike",
                          "train_tube", "bus"), names(od))
od_df <- sf::st_drop_geometry(od)[, keep_cols]
write.csv(od_df, "data/leeds_pct_od.csv", row.names = FALSE)

zones_out <- zones[, c("geo_code", "geo_name")]
sf::st_write(zones_out, "data/leeds_pct_zones_msoa.geojson", delete_dsn = TRUE, quiet = TRUE)

cat("Saved data/leeds_pct_od.csv (", nrow(od_df), "rows) and data/leeds_pct_zones_msoa.geojson (", nrow(zones_out), "zones)\n")
