import logging
# import sys

# import geopy
import s2sphere
# import math

# from utils.collections import Location
# from utils.geo import get_middle_of_coord_list, get_distance_of_two_points_in_meters

log = logging.getLogger(__name__)


class S2Helper:
    @staticmethod
    def lat_lng_to_cell_id(lat, lng, level=10):
        region_cover = s2sphere.RegionCoverer()
        region_cover.min_level = level
        region_cover.max_level = level
        region_cover.max_cells = 1
        p1 = s2sphere.LatLng.from_degrees(lat, lng)
        p2 = s2sphere.LatLng.from_degrees(lat, lng)
        covering = region_cover.get_covering(s2sphere.LatLngRect.from_point_pair(p1, p2))
        # we will only get our desired cell ;)
        return covering[0].id()

    # RM stores lat, long as well...
    # returns tuple  <lat, lng>
    @staticmethod
    def middle_of_cell(cell_id):
        cell = s2sphere.CellId(cell_id)
        lat_lng = cell.to_lat_lng()
        return lat_lng.lat().degrees, lat_lng.lng().degrees

    @staticmethod
    def calc_s2_cells(north, south, west, east, cell_size=16):
        centers_in_area = []
        region = s2sphere.RegionCoverer()
        region.min_level = cell_size
        region.max_level = cell_size
        p1 = s2sphere.LatLng.from_degrees(north, west)
        p2 = s2sphere.LatLng.from_degrees(south, east)
        cell_ids = region.get_covering(
            s2sphere.LatLngRect.from_point_pair(p1, p2))
        log.debug('Detecting ' + str(len(cell_ids)) +
              ' L{} Cells in Area'.format(str(cell_size)))
        for cell_id in cell_ids:
            split_cell_id = str(cell_id).split(' ')
            position = S2Helper.get_position_from_cell(int(split_cell_id[1], 16))
            centers_in_area.append([position[0], position[1]])
            # calc_route_data.append(str(position[0]) + ', ' + str(position[1]))

        return centers_in_area

    @staticmethod
    def get_position_from_cell(cell_id):
        cell = s2sphere.CellId(id_=int(cell_id)).to_lat_lng()
        return s2sphere.math.degrees(cell.lat().radians), \
               s2sphere.math.degrees(cell.lng().radians), 0
               
    @staticmethod    
    def get_s2_cells_from_fence(geofence, cell_size=16):
        _geofence = geofence
        log.warning("Calculating corners of fences")
        south, east, north, west= _geofence.get_polygon_from_fence()
        calc_route_data = []
        region = s2sphere.RegionCoverer()
        region.min_level = cell_size
        region.max_level = cell_size
        p1 = s2sphere.LatLng.from_degrees(north, west)
        p2 = s2sphere.LatLng.from_degrees(south, east)
        log.warning("Calculating coverage of region")
        cell_ids = region.get_covering(
            s2sphere.LatLngRect.from_point_pair(p1, p2))

        log.warning("Iterating cell_ids")
        for cell_id in cell_ids:
            split_cell_id = str(cell_id).split(' ')
            position = S2Helper.middle_of_cell(int(split_cell_id[1], 16))
            calc_route_data.append([position[0], position[1]])
        log.debug('Detecting ' + str(len(calc_route_data)) +
                 ' L{} Cells in Area'.format(str(cell_size)))

        return calc_route_data

# the following stuff is drafts for further consideration
    # @staticmethod
    # def _generate_locations(distance, geofence_helper):
    #     results = []
    #     south, east, north, west = geofence_helper.get_polygon_from_fence()
    #
    #     corners = [
    #             Location(south, east),
    #             Location(south, west),
    #             Location(north, east),
    #             Location(north, west)
    #         ]
    #     # get the center
    #     center = get_middle_of_coord_list(corners)
    #     results.append([center.lat, center.lng])
    #
    #     # get the farthest to the center...
    #     farthest_dist = 0
    #     for corner in corners:
    #         dist_temp = get_distance_of_two_points_in_meters(center.lat, center.lng, corner.lat, corner.lng)
    #         if dist_temp > farthest_dist:
    #             farthest_dist = dist_temp
    #
    #     # calculate step_limit, round up to reduce risk of losing stuff
    #     step_limit = math.ceil(farthest_dist / distance)
    #
    #     # This will loop thorugh all the rings in the hex from the centre
    #     # moving outwards
    #     for ring in range(1, step_limit):
    #         for i in range(0, 6):
    #             # Star_locs will contain the locations of the 6 vertices of
    #             # the current ring (90,150,210,270,330 and 30 degrees from
    #             # origin) to form a star
    #             star_loc = S2Helper.get_new_coords(center, distance * ring,
    #                                                90 + 60 * i)
    #             for j in range(0, ring):
    #                 # Then from each point on the star, create locations
    #                 # towards the next point of star along the edge of the
    #                 # current ring
    #                 loc = S2Helper.get_new_coords(star_loc, distance * j, 210 + 60 * i)
    #                 results.append([loc.lat, loc.lng])
    #
    #     # Geofence results.
    #     if geofence_helper is not None and geofence_helper.is_enabled():
    #         results = geofence_helper.get_geofenced_coordinates(results)
    #         if not results:
    #             log.error('No cells regarded as valid for desired scan area. '
    #                       'Check your provided geofences. Aborting.')
    #             sys.exit(1)
    #
    #     return results
    #
    # @staticmethod
    # # Returns destination coords given origin coords, distance (Kms) and bearing.
    # def get_new_coords(init_loc, distance, bearing):
    #     """
    #     Given an initial lat/lng, a distance(in kms), and a bearing (degrees),
    #     this will calculate the resulting lat/lng coordinates.
    #     """
    #     origin = geopy.Point(init_loc.lat, init_loc.lng)
    #     destination = geopy.distance.distance(kilometers=distance).destination(
    #         origin, bearing)
    #     return Location(destination.latitude, destination.longitude)
