from enum import StrEnum

#: Table name for saving the results of the analysis at 100m resolution
CENSUS_HOSPITAL_ROUTE_TABLE_100M = "census_hospital_route_100m"

#: Table name for saving the results of the analysis at 1km resolution
CENSUS_HOSPITAL_ROUTE_TABLE_1KM = "census_hospital_route_1km"

#: Table name for saving the results of the analysis at 10km resolution
CENSUS_HOSPITAL_ROUTE_TABLE_10KM = "census_hospital_route_10km"

#: Table name for saving from-census results at 100m resolution
CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_100M = "census_hospital_route_from_census_100m"

#: Table name for saving from-census results at 1km resolution
CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_1KM = "census_hospital_route_from_census_1km"

#: Table name for saving from-census results at 10km resolution
CENSUS_HOSPITAL_ROUTE_TABLE_FROM_CENSUS_10KM = "census_hospital_route_from_census_10km"

#: Name of the app for use in loggers and other things
APP_NAME = "ems_germany_analysis"

class ResolutionSuffix(StrEnum):
    """
    Acceptable resolution suffixes (100m, 1km and 10km)

    Corresponds to the data available in the Zensus 2022 dataset
    """
    m100 = "100m"
    km1 = "1km"
    km10 = "10km"
