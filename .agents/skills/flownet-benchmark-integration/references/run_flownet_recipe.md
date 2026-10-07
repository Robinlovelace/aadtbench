# Working flownet R script (copy + adapt)

Verified on Leuven walk network (19,118 edges). Writes `edge_idx, flow` with
`edge_idx` 0-based = network GPKG read order, so a Python wrapper matches it to
`geopandas reset_index()` integer positions.

```r
#!/usr/bin/env Rscript
# Usage: Rscript run_flownet_assignment.R <network_gpkg> <origins_geojson> \
#        <destinations_geojson> <cost> <beta> <detour_max> <out_csv> [<mode>] [<od_sample>]
options(error = function(e) {
  cat("ERROR:", conditionMessage(e), "\n")
  if (interactive()) recover() else quit(save = "no", status = 1)
})

suppressMessages(library(flownet))
suppressMessages(library(sf))
suppressMessages(library(igraph))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 7) stop("Usage: run_flownet_assignment.R network origins destinations cost beta detour_max out_csv [mode] [od_sample]")

network_path <- args[1]; origins_path <- args[2]; destinations_path <- args[3]
cost_col <- args[4]
beta <- as.numeric(args[5])          # accepted, currently unused
detour_max <- as.numeric(args[6])     # accepted, currently unused
out_csv <- args[7]
mode <- ifelse(length(args) >= 8, args[8], "walk")
od_sample <- ifelse(length(args) >= 9 && nzchar(args[9]), as.integer(args[9]), 300L)

net <- st_read(network_path, quiet = TRUE)
if (!all(st_geometry_type(net) %in% c("LINESTRING", "MULTILINESTRING")))
  stop("Network layer must contain LINESTRING geometries for flownet")

# DIRECTED graph — keeps nrow(gr) == nrow(net) so final_flows aligns 1:1.
# Do NOT add create_undirected_graph()/normalize_graph(): they consolidate edges
# and break the edge-order mapping back to the network.
gr <- linestrings_to_graph(net)

origins <- st_read(origins_path, quiet = TRUE)
destinations <- st_read(destinations_path, quiet = TRUE)
net_crs <- st_crs(net)
if (!is.na(net_crs) && !identical(st_crs(origins), net_crs)) origins <- st_transform(origins, net_crs)
if (!is.na(net_crs) && !identical(st_crs(destinations), net_crs)) destinations <- st_transform(destinations, net_crs)
if (!"population" %in% names(origins)) stop("Origins must have a 'population' column")
if (!"attractor_weight" %in% names(destinations)) stop("Destinations must have an 'attractor_weight' column")

# Subsample top-weighted zones so the OD matrix stays tractable.
if (nrow(origins) > od_sample) origins <- origins[order(-as.numeric(origins$population))[seq_len(od_sample)], ]
if (nrow(destinations) > od_sample) destinations <- destinations[order(-as.numeric(destinations$attractor_weight))[seq_len(od_sample)], ]

nodes <- nodes_from_graph(gr, sf = TRUE)
orig_near <- nodes$node[st_nearest_feature(origins, nodes)]
dest_near <- nodes$node[st_nearest_feature(destinations, nodes)]

od_nodes <- unique(c(orig_near, dest_near)); n_zones <- length(od_nodes)
od_matrix <- matrix(0, n_zones, n_zones)
rownames(od_matrix) <- od_nodes; colnames(od_matrix) <- od_nodes
for (i in seq_along(orig_near)) {
  o <- orig_near[i]; w_o <- as.numeric(origins$population[i])
  for (j in seq_along(dest_near)) {
    d <- dest_near[j]; w_d <- as.numeric(destinations$attractor_weight[j])
    od_matrix[as.character(o), as.character(d)] <- w_o * w_d
  }
}
od_long <- melt_od_matrix(od_matrix, nodes = od_nodes)

# Canonical minimal call (method/beta/detour.max extras triggered internal errors here).
res <- run_assignment(gr, od_long, cost.column = cost_col)

out_df <- data.frame(edge_idx = seq_len(nrow(net)) - 1, flow = res$final_flows)
write.csv(out_df, out_csv, row.names = FALSE)
cat(sprintf("flownet %s: assigned %d edges, total flow %.0f\n",
            mode, sum(!is.na(res$final_flows)), sum(res$final_flows, na.rm = TRUE)))
```

## Reproduction recipe (REPL, fast with od_sample=150)

```r
suppressMessages({library(flownet); library(sf); library(igraph)})
net <- st_read("data/leuven_walk_edges.gpkg", quiet=TRUE)
gr <- linestrings_to_graph(net)   # 19118 edges, 1:1 with net
origins <- st_transform(st_read("data/leuven_worldpop_origins.geojson", quiet=TRUE), st_crs(net))
destinations <- st_transform(st_read("data/leuven_attractors.geojson", quiet=TRUE), st_crs(net))
origins <- origins[order(-as.numeric(origins$population))[1:150],]
destinations <- destinations[order(-as.numeric(destinations$attractor_weight))[1:150],]
nodes <- nodes_from_graph(gr, sf=TRUE)
orig_near <- nodes$node[st_nearest_feature(origins, nodes)]
dest_near <- nodes$node[st_nearest_feature(destinations, nodes)]
od_nodes <- unique(c(orig_near, dest_near))
od_matrix <- matrix(0, length(od_nodes), length(od_nodes))
rownames(od_matrix) <- od_nodes; colnames(od_matrix) <- od_nodes
for (i in seq_along(orig_near)) for (j in seq_along(dest_near))
  od_matrix[as.character(orig_near[i]), as.character(dest_near[j])] <-
    as.numeric(origins$population[i]) * as.numeric(destinations$attractor_weight[j])
od_long <- melt_od_matrix(od_matrix, nodes=od_nodes)
res <- run_assignment(gr, od_long, cost.column=".length")
# nrow(gr)=19118, length(res$final_flows)=19118, sum≈9.1e8
```
