# Emergency Medical Service Analysis for Germany

## 2026-03-22

### Reproducing

I would like this repository to contain all the steps you need to
go through to reproduce this work. So far, that involves the following:

1. `pixi` to create a postgresql instance
2. `pgosm-flex` (my version) to create a Germany database
3. `zensus2pgsql` to import census data to postgres
4. OpenRoutingService to launch a server that is used to calculate
   route costs for the whole country of Germany
5. `krankenhausverzeichnis` to download an import the hospital data to database
   i. I'm going to just move this over to this tool


