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


 