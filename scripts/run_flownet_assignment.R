#!/usr/bin/env Rscript
# Run flownet traffic assignment for one benchmark mode and write assigned
# edge flows to CSV for downstream metric computation.
#
# Two demand paths are supported:
#   A) REAL OD (Leeds drive): a census OD csv (geo_code1, geo_code2, <flow col>)
#      + a zones geojson (geo_code, geometry). Zone centroids are snapped to
#      nearest network nodes (<= 500 m) and the OD is melted to long format
#      (from, to, flow).
#   B) GRAVITY (Leuven): WorldPop origins x OSM attractor destinations weighted
#      by population x attractor_weight (legacy path).
#
# All flownet 0.3.0 assignment parameters are now actually passed through:
# method (PSL/AoN), beta, detour.max, angle.max, nthreads (mirai), plus a
# cost divisor (cost_div) to rescale the cost column (e.g. meters -> km) so
# the PSL logit is not degenerate at meter scale.
#
# Usage (driven by scripts/bench_flownet.py):
#   Rscript run_flownet_assignment.R <network_gpkg> <origins_geojson>
#       <destinations_geojson> <cost> <beta> <detour_max> <out_csv>
#       [mode] [od_sample] [od_file] [zones_file] [method] [angle_max]
#       [nthreads] [cost_div]
#
# Output CSV columns: edge_idx, flow
# where edge_idx is 0-based and aligns 1:1 with the rows of network_gpkg
# (read order), so the Python wrapper can join flows back to network edges.

options(error = function(e) {
  cat("ERROR:", conditionMessage(e), "\n")
  if (interactive()) recover() else quit(save = "no", status = 1)
})

suppressMessages(library(flownet))
suppressMessages(library(sf))
suppressMessages(library(igraph))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 7) {
  stop("Usage: run_flownet_assignment.R network origins destinations cost beta detour_max out_csv [mode] [od_sample] [od_file] [zones_file] [method] [angle_max] [nthreads] [cost_div]")
}

network_path <- args[1]
origins_path <- args[2]
destinations_path <- args[3]
cost_col <- args[4]
beta <- as.numeric(args[5])
detour_max <- as.numeric(args[6])
out_csv <- args[7]
mode <- ifelse(length(args) >= 8, args[8], "walk")
od_sample <- ifelse(length(args) >= 9 && nzchar(args[9]), as.integer(args[9]), 150L)
od_file <- ifelse(length(args) >= 10, args[10], "")
zones_file <- ifelse(length(args) >= 11, args[11], "")
method <- ifelse(length(args) >= 12 && nzchar(args[12]), args[12], "PSL")
angle_max <- ifelse(length(args) >= 13 && nzchar(args[13]), as.numeric(args[13]), 90)
nthreads <- ifelse(length(args) >= 14 && nzchar(args[14]), as.integer(args[14]), 1L)
cost_div <- ifelse(length(args) >= 15 && nzchar(args[15]), as.numeric(args[15]), 1)
# cost_type: "length" = plain edge length; "imp" = length x dimensionless
# highway-class impedance factor (baseline_speed / class_speed), mirroring the
# cityseer_od 'dimensionless_imp' variant that scores best on Leeds AADT.
cost_type <- ifelse(length(args) >= 16 && nzchar(args[16]), args[16], "length")
MAX_SNAP_DIST <- 500  # metres, matches the Python benchmark convention

# Free-flow mph by OSM highway class (mirrors scripts/bench_cityseer_od.py)
CLASS_MPH <- c(motorway = 65, motorway_link = 40, trunk = 55, trunk_link = 35,
               primary = 35, primary_link = 25, secondary = 30, secondary_link = 25,
               tertiary = 25, tertiary_link = 20, unclassified = 22,
               residential = 18, living_street = 10)
DEFAULT_MPH <- 20
MPH_TO_MS <- 0.44704
BASELINE_MS <- 8.3  # drive mode speed, matches MODE_SPEEDS in scripts/config.py

use_real_od <- nzchar(od_file) && nzchar(zones_file) &&
  file.exists(od_file) && file.exists(zones_file)

# ── Load network as flownet graph ──
net <- st_read(network_path, quiet = TRUE)
if (!all(st_geometry_type(net) %in% c("LINESTRING", "MULTILINESTRING"))) {
  stop("Network layer must contain LINESTRING geometries for flownet")
}
gr <- linestrings_to_graph(net)
net_crs <- st_crs(net)

# Cost vector: flownet's PSL utility is V = -cost + beta*ln(PS), so with cost
# in metres (~10^3) the logit is degenerate (all mass on the shortest path)
# and beta has no visible effect. cost_div rescales (e.g. /1000 for km).
# cost_type "imp" multiplies by a dimensionless highway-class speed factor so
# major roads (motorways/trunks) are relatively cheaper -- the single biggest
# lever found for cityseer_od vs DfT AADT on Leeds.
length_vec <- gr[[".length"]]
if (cost_type == "imp") {
  cls <- tolower(as.character(gr[["highway"]]))
  cls[cls == "" | is.na(cls)] <- "unclassified"
  mph <- unname(CLASS_MPH[cls])
  mph[is.na(mph)] <- DEFAULT_MPH
  imp_factor <- BASELINE_MS / (mph * MPH_TO_MS)
  cost_vec <- length_vec * imp_factor / cost_div
} else {
  cost_vec <- length_vec / cost_div
}
if (length(cost_vec) != nrow(gr)) {
  stop(sprintf("cost column '%s' not found on flownet graph", cost_col))
}

# ── Build OD (real census OD if available, else gravity) ──
if (use_real_od) {
  od_df <- read.csv(od_file, stringsAsFactors = FALSE)
  zones <- st_read(zones_file, quiet = TRUE)
  if (!is.na(net_crs) && !identical(st_crs(zones), net_crs)) {
    zones <- st_transform(zones, net_crs)
  }
  flow_col <- if ("car_driver" %in% names(od_df)) "car_driver" else
    if ("all" %in% names(od_df)) "all" else names(od_df)[ncol(od_df)]
  zones$centroid <- st_centroid(st_geometry(zones))

  nodes <- nodes_from_graph(gr, sf = TRUE)

  # Top-N zone cap by total OD flow (in+out), preserving the dense core.
  if (nrow(zones) > od_sample) {
    # tapply results have different factor levels for origins vs destinations,
    # so add with a union of all zone codes (avoids "non-conformable arrays").
    all_codes <- union(as.character(od_df$geo_code1), as.character(od_df$geo_code2))
    zflow <- tapply(od_df[[flow_col]], factor(as.character(od_df$geo_code1), levels = all_codes), sum)
    zflow2 <- tapply(od_df[[flow_col]], factor(as.character(od_df$geo_code2), levels = all_codes), sum)
    zflow[is.na(zflow)] <- 0
    zflow2[is.na(zflow2)] <- 0
    zflow <- zflow + zflow2
    keep <- names(sort(zflow, decreasing = TRUE))[seq_len(min(od_sample, length(zflow)))]
    zones <- zones[zones$geo_code %in% keep, ]
  }

  near_idx <- st_nearest_feature(zones$centroid, nodes)
  near_dist <- as.numeric(st_distance(zones$centroid, nodes[near_idx, ], by_element = TRUE))
  zone_node <- setNames(nodes$node[near_idx], zones$geo_code)
  zone_node <- zone_node[near_dist <= MAX_SNAP_DIST]

  o_ok <- od_df$geo_code1 %in% names(zone_node)
  d_ok <- od_df$geo_code2 %in% names(zone_node)
  f <- as.numeric(od_df[[flow_col]])
  keep <- o_ok & d_ok & is.finite(f) & f > 0
  from <- unname(zone_node[od_df$geo_code1[keep]])
  to <- unname(zone_node[od_df$geo_code2[keep]])
  f <- f[keep]
  # Drop intra-zone pairs (same node) - meaningless for assignment.
  nz <- from != to
  od_long <- data.frame(from = from[nz], to = to[nz], flow = f[nz])
  cat(sprintf("real OD: %d zones snapped, %d pairs, total flow %.0f\n",
              length(zone_node), nrow(od_long), sum(od_long$flow)))
} else {
  # ── Gravity OD (WorldPop origins x attractor destinations) ──
  origins <- st_read(origins_path, quiet = TRUE)
  destinations <- st_read(destinations_path, quiet = TRUE)
  if (!is.na(net_crs) && !identical(st_crs(origins), net_crs)) {
    origins <- st_transform(origins, net_crs)
  }
  if (!is.na(net_crs) && !identical(st_crs(destinations), net_crs)) {
    destinations <- st_transform(destinations, net_crs)
  }
  if (!"population" %in% names(origins)) {
    stop("Origins must have a 'population' column")
  }
  if (!"attractor_weight" %in% names(destinations)) {
    stop("Destinations must have an 'attractor_weight' column")
  }
  if (nrow(origins) > od_sample) {
    origins <- origins[order(-as.numeric(origins$population))[seq_len(od_sample)], ]
  }
  if (nrow(destinations) > od_sample) {
    destinations <- destinations[order(-as.numeric(destinations$attractor_weight))[seq_len(od_sample)], ]
  }
  nodes <- nodes_from_graph(gr, sf = TRUE)
  orig_near <- nodes$node[st_nearest_feature(origins, nodes)]
  dest_near <- nodes$node[st_nearest_feature(destinations, nodes)]
  od_nodes <- unique(c(orig_near, dest_near))
  n_zones <- length(od_nodes)
  od_matrix <- matrix(0, n_zones, n_zones)
  rownames(od_matrix) <- od_nodes
  colnames(od_matrix) <- od_nodes
  for (i in seq_along(orig_near)) {
    o <- orig_near[i]
    w_o <- as.numeric(origins$population[i])
    for (j in seq_along(dest_near)) {
      d <- dest_near[j]
      w_d <- as.numeric(destinations$attractor_weight[j])
      od_matrix[as.character(o), as.character(d)] <- w_o * w_d
    }
  }
  od_long <- melt_od_matrix(od_matrix, nodes = od_nodes)
  cat(sprintf("gravity OD: %d pairs, total flow %.0f\n",
              nrow(od_long), sum(od_long$flow)))
}

if (nrow(od_long) == 0) {
  stop("OD matrix is empty after filtering")
}

# ── Run assignment with FULL parameter pass-through ──
# NOTE: do.call is required, not a direct call: flownet parallelises the
# per-OD-pair loop with mirai daemons, and R's lazy argument promises (e.g.
# `detour.max = detour_max`) resolve against THIS script's environment, which
# is NOT serialised to the daemons -> "object 'detour_max' not found" in the
# mirai workers. do.call evaluates the values eagerly so the daemons receive
# literals. (This is the real cause of the old "beta/detour.max internal
# error" note, which predates flownet 0.3.0's nthreads support.)
res <- tryCatch(
  do.call(run_assignment, list(
    graph_df = gr, od_matrix_long = od_long, cost.column = cost_vec,
    method = method, beta = beta, detour.max = detour_max,
    angle.max = angle_max, nthreads = nthreads, verbose = FALSE
  )),
  error = function(e) {
    msg <- conditionMessage(e)
    con <- file("/tmp/fn_real_err.txt", open = "wt")
    writeLines(c(paste("CALL:", paste(args, collapse = " ")), "", "RUN_ASSIGNMENT ERROR:", msg), con)
    close(con)
    stop(msg)
  }
)

# Map final flows back onto the original network edge order.
flows <- res$final_flows

out_df <- data.frame(edge_idx = seq_len(nrow(net)) - 1, flow = flows)
write.csv(out_df, out_csv, row.names = FALSE)
cat(sprintf("flownet %s method=%s beta=%g detour=%g: assigned %d edges, total flow %.0f\n",
            mode, method, beta, detour_max, sum(!is.na(flows)), sum(flows, na.rm = TRUE)))
