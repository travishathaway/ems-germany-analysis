-- Step one: created a buffered version of Germany

CREATE TABLE ems_germany_analysis.germany_buffered AS 
select name, st_buffer(geom, 1000) as geom from osm_germany.place_polygon_nested where name = 'Germany';

-- Step two: 

--Create table ems_germany_analysis.berlin_pop AS
WITH berlin AS (
    SELECT ST_Union(geom) as geom FROM osm_germany.place_polygon_nested WHERE name in ('Berlin')
)
SELECT
    p.gitter_id_100m,
	p.insgesamt_bevoelkerung,
	p.unter18,
	p.a18bis29,
	p.a30bis49,
	p.a50bis64,
	p.a65undaelter,
	p.geom,
	h.notfall as level,
    COUNT(h.geom) AS hospitals_within_10k
FROM
    zensus.alter_in_5_altersklassen_100m p
JOIN
    berlin b ON ST_Contains(b.geom, p.geom)
LEFT JOIN
    public.notfall_krankenhauser_geocoded h
    ON ST_DWithin(p.geom, h.geom, 10000)
GROUP BY
	p.gitter_id_100m,
	p.insgesamt_bevoelkerung,
	p.unter18,
	p.a18bis29,
	p.a30bis49,
	p.a50bis64,
	p.a65undaelter,
	p.geom,
	h.notfall
ORDER BY
	p.gitter_id_100m;
	
CREATE TABLE ems_germany_analysis.germany_hospital_accessibility_10km AS
	SELECT
	    p.gitter_id_100m,
	    p.insgesamt_bevoelkerung,
	    p.unter18,
	    p.a18bis29,
	    p.a30bis49,
	    p.a50bis64,
	    p.a65undaelter,
	    p.geom,
	    COUNT(h.geom) FILTER (WHERE h.notfall = '1.0') AS level_1,
	    COUNT(h.geom) FILTER (WHERE h.notfall = '2.0') AS level_2,
	    COUNT(h.geom) FILTER (WHERE h.notfall = '3.0') AS level_3
	FROM
	    zensus.alter_in_5_altersklassen_100m p
	LEFT JOIN
	    public.notfall_krankenhauser_geocoded h
	ON
		ST_DWithin(p.geom, h.geom, 10000)
	GROUP BY
	    p.gitter_id_100m,
	    p.insgesamt_bevoelkerung,
	    p.unter18,
	    p.a18bis29,
	    p.a30bis49,
	    p.a50bis64,
	    p.a65undaelter,
	    p.geom
	ORDER BY
	    p.gitter_id_100m;


-- Creates road network around center of Berlin
CALL osm_germany.routing_prepare_road_network(
      ST_SetSRID(ST_MakePoint(13.405, 52.520), 4326),
      20000.0
  );

select * from ems_germany_analysis.notfall_krankenhauser_geocoded;

-- cumulative percentage buckets

  WITH min_costs AS (
      SELECT                                                                                                                                      
          r.gitter_id,
          h.notfall,                                                                                                                              
          min(r.total_cost_seconds) AS min_cost                                                                                                   
      FROM ems_germany_analysis.census_hospital_route_from_census_1km r
      JOIN ems_germany_analysis.notfall_krankenhauser_geocoded h ON r.hospital_id = h.id                                                          
      GROUP BY r.gitter_id, h.notfall                                                                                                             
  ),                                                                                                                                              
  cell_data AS (                                                                                                                                  
      SELECT      
          r.notfall,
          r.min_cost,                                                                                                                             
          CASE
              WHEN r.min_cost <  300 THEN '1_under_5min'                                                                                          
              WHEN r.min_cost <  600 THEN '2_5_to_10min'                                                                                          
              WHEN r.min_cost <  900 THEN '3_10_to_15min'
              WHEN r.min_cost < 1200 THEN '4_15_to_20min'                                                                                         
              WHEN r.min_cost < 1800 THEN '5_20_to_30min'
              ELSE                        '6_over_30min'                                                                                          
          END                                                     AS bucket,                                                                      
          z.a65undaelter                                          AS pop_65_plus,                                                                 
          z.unter18 + z.a18bis29 + z.a30bis49 + z.a50bis64      AS pop_under_65                                                                   
      FROM min_costs r                                                                                                                            
      JOIN zensus.alter_in_5_altersklassen_1km z ON z.gitter_id_1km = r.gitter_id                                                                 
  ),                                                                                                                                              
  bucket_totals AS (
      SELECT                                                                                                                                      
          notfall,
          bucket,
          sum(pop_65_plus)    AS pop_65_plus,                                                                                                     
          sum(pop_under_65)   AS pop_under_65                                                                                                     
      FROM cell_data                                                                                                                              
      GROUP BY notfall, bucket                                                                                                                    
  )               
  SELECT                                                                                                                                          
      notfall,    
      bucket,
      pop_65_plus,
      pop_under_65,                                                                                                                               
      -- share within each bucket
      round(100.0 * pop_65_plus  / sum(pop_65_plus)  OVER (PARTITION BY notfall), 1) AS pct_65_plus,                                              
      round(100.0 * pop_under_65 / sum(pop_under_65) OVER (PARTITION BY notfall), 1) AS pct_under_65,                                             
      -- cumulative share (what % lives within this threshold or better)                                                                          
      round(100.0 * sum(pop_65_plus)  OVER (PARTITION BY notfall ORDER BY bucket) / sum(pop_65_plus)  OVER (PARTITION BY notfall), 1) AS          
  cumulative_pct_65_plus,                                                                                                                         
      round(100.0 * sum(pop_under_65) OVER (PARTITION BY notfall ORDER BY bucket) / sum(pop_under_65) OVER (PARTITION BY notfall), 1) AS          
  cumulative_pct_under_65                                                                                                                         
  FROM bucket_totals
  ORDER BY notfall, bucket         

 