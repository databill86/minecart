u"""
This module contains the objects representing graphics elements in a document.
"""

import pdfminer.utils
import sys


class GraphicsObject(object):

    """
    An abstract base class for the graphical objects found on a page.
    """

    def get_bbox(self):
        """
        Return the bounding box for the graphics object.

        The return value is a 4-tuple of the form (left, bottom, right, top)

        """
        raise NotImplementedError

    def check_inside_bbox(self, bbox):
        "Check whether the given shape fits inside the given bounding box."
        left, bottom, right, top = self.get_bbox()
        return (left >= bbox[0]
                and bottom >= bbox[1]
                and right <= bbox[2]
                and top <= bbox[3])


class GraphicsCollection(list):

    """
    A collection of several graphics objects.
    """

    def iter_in_bbox(self, bbox):
        """
        Iterate over all shapes in the given bounding box.

        `bbox` -- a 4-tuple of the form (left, bottom, right, top)

        """
        for shape in self:
            if shape.check_inside_bbox(bbox):
                yield shape

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__,
                               ", ".join(repr(item) for item in self))


def b_spline_bbox(point_0, point_1, point_2, point_3):
    "Calculates a bounding box for the given spline segment."
    # Code translated from http://stackoverflow.com/questions/2587751/
    # It is based on calculating the first derivative of the bspline, and
    # finding all the extrema of the parametrized form, and taking the
    # bounding box of that
    #pylint: disable=C0103
    t_values = [0, 1]
    for i in (0, 1):  # Does x values first then y values
        # The following are the coefficients of the spline's derivative
        a = -3 * point_0[i] + 9 * point_1[i] - 9 * point_2[i] + 3 * point_3[i]
        b = 6 * point_0[i] - 12 * point_1[i] + 6 * point_2[i]
        c = 3 * point_1[i] - 3 * point_0[i]
        if abs(a) < sys.float_info.min:  # Numerical robustness checks
            if abs(b) < sys.float_info.min:
                # The spline is linear in this coordinate (or a single
                # point), just need to check the two endpoints
                continue
            # The spline is quadratic with a single extremum:
            t = -c / b
            if 0 < t < 1:
                t_values.append(t)
                continue
        b2ac = b * b - 4 * c * a
        if b2ac < 0:
            continue
        sqrtb2ac = b2ac ** .5
        t1 = (-b + sqrtb2ac) / (2 * a)
        if 0 < t1 < 1:
            t_values.append(t1)
        t2 = (-b - sqrtb2ac) / (2 * a)
        if 0 < t2 < 1:
            t_values.append(t2)

    x0, y0 = point_0[0]
    x1, y1 = point_1[0]
    x2, y2 = point_2[0]
    x3, y3 = point_3[0]
    x_bounds = []
    y_bounds = []
    for t in t_values:
        mt = 1 - t
        x = (mt ** 3 * x0
             + 3 * mt ** 2 * t * x1
             + 3 * mt * t ** 2 * x2
             + t ** 3 * x3)
        y = (mt ** 3 * y0
             + 3 * mt ** 2 * t * y1
             + 3 * mt * t ** 2 * y2
             + t ** 3 * y3)
        x_bounds.append(x)
        y_bounds.append(y)
    return min(x_bounds), min(y_bounds), max(x_bounds), max(y_bounds)


class Shape(GraphicsObject):

    """
    A Shape on a Page. Can be a path when stroked or filled.

    `graphicstate` --
    `stroked` -- A boolean indicating whether the path is stroked
    `filled` -- A boolean indicating whether the path is filled
    `evenodd` -- A boolean indicating whether to use the Even/Odd rule to
                 determine the path interior. If False, the Winding Number
                 Rule is used instead.
    `path` -- A sequence of path triples (type, *coords), where type is one of

              - m: Moveto
              - l: Lineto
              - c: Curveto
              - h: Close subpath
              - v: Curveto (1st control point on first point)
              - y: Curveto (2nd control point on last point)

              And coords is a sequence of (flat) coordinate values describing
              the path construction operator to use.

    """

    def __init__(self, graphicstate, stroke, fill, evenodd, path):
        super(Shape, self).__init__()
        self.graphicstate = graphicstate.copy()
        self.stroked = stroke
        self.filled = fill
        self.evenodd = evenodd
        self.path = path
        self._bbox = None

    def get_bbox(self):
        "Returns a minimal bounding box for the curve."
        if self._bbox is None:
            cur_path = []
            points = []
            for segment in self.path:
                kind = segment[0]
                if kind == 'm':
                    if len(cur_path) > 1: # ignore repeated movetos
                        points.extend(cur_path)
                    cur_path = list(segment[1:])
                elif kind == 'l':
                    cur_path.extend(segment[1:])
                elif kind in 'cvy':
                    if kind == 'c':
                        spline = (cur_path[-1], segment[1:3],
                                  segment[3:5], segment[5:7])
                    elif kind == 'v':
                        spline = (cur_path[-1], cur_path[-1],
                                  segment[1:3], segment[3:5])
                    elif kind == 'y':
                        spline = (cur_path[-1], segment[1:3],
                                  segment[3:5], segment[3:5])
                    # We replace the curve by a zig-zag line through the
                    # corners of the curve's bounding box
                    cur_path.extend(b_spline_bbox(*spline))
                    cur_path.extend(segment[5:7])
                elif kind == 'h':
                    points.extend(cur_path)
                    cur_path = []
            exes = points[::2]
            whys = points[1::2]
            self._bbox = (min(exes), min(whys), max(exes), max(whys))
        return self._bbox


class Image(GraphicsObject):

    """
    Represents an image on a page.

    `ctm` -- Current Transformation Matrix in the graphicstate
    `obj` -- The PDFStream object representing the image

    """

    def __init__(self, ctm, obj):
        super(Image, self).__init__()
        self.ctm = ctm
        self.obj = obj
        #pylint: disable=C0103
        self.coords = (x1, y1), (x2, y2), (x3, y3), (x4, y4) = (
            pdfminer.utils.apply_matrix_pt(self.ctm, (0, 0)),
            pdfminer.utils.apply_matrix_pt(self.ctm, (0, 1)),
            pdfminer.utils.apply_matrix_pt(self.ctm, (1, 1)),
            pdfminer.utils.apply_matrix_pt(self.ctm, (1, 0)),
        )
        self.bbox = (
            min(x1, x2, x3, x4),
            min(y1, y2, y3, y4),
            max(x1, x2, x3, x4),
            max(y1, y2, y3, y4),
        )

    def get_bbox(self):
        return self.bbox

class Lettering(unicode, GraphicsObject):

    """
    A text string on a page, including its typographic information.
    """

    def __new__(cls, data, bbox, horizontal=True):
        loc_str = unicode.__new__(cls, data)
        x1, y1, x2, y2 = bbox  #pylint: disable=C0103
        loc_str.bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        loc_str.horizontal = horizontal
        return loc_str

    def get_bbox(self):
        return self.bbox

    def __repr__(self):
        return "<%s: %s %r>" % (self.__class__.__name__, self, self.bbox)


class Page(object):

    """
    A page in the document, which contains all the graphics elements.

    Has the following attributes:

    * `images` -- a `GraphicsCollection` with all the `Image` objects on the
                  page
    * `letterings` -- a `GraphicsCollection` containing all the text objects
                      found on the page (as `Lettering`s)
    * `shapes` -- a `GraphicsCollection` with all the `Shape` objects on the
                  page

    """

    def __init__(self):
        self.images = GraphicsCollection()
        self.letterings = GraphicsCollection()
        self.shapes = GraphicsCollection()

    def add_shape(self, shape):
        "Add the given shape to the page."
        self.shapes.append(shape)

    def add_image(self, image):
        "Add the given image to the page."
        self.images.append(image)

    def add_lettering(self, lettering):
        "Add the given lettering to the page."
        self.letterings.append(lettering)
