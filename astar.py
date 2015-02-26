from coordinates import block_coords

class AStarNode:
    def __init__(self, coords, parent, finish_coords):
        self.coords = coords
        self.parent = parent
        if parent is None:
            if coords == finish_coords:
                self.prev_dist = float('inf') # finish
            else:
                self.prev_dist = 0 # start
        else:
            self.prev_dist = parent.prev_dist + 1
        # rectangular distance to finish
        self.estim_dist = sum([abs(coords[i] - finish_coords[i]) for i in range(len(coords))])

    def __repr__(self):
        if self.parent is None:
            return 'Source%s' % str(self.coords)
        #return 'Node(%i %i %i)' % self.coords
        return 'Node(c=%s p=%s pd=%s ed=%s td=%s)' % (self.coords, (self.parent.coords if self.parent is not None else 'None'), self.prev_dist, self.estim_dist, self.prev_dist + self.estim_dist)

    def c_add(self, *coords):
        """ Returns the translation of coords by self.coords. """
        assert len(coords) == len(self.coords)
        return tuple([coords[i] + self.coords[i] for i in range(len(coords))])

    def is_valid(self, world):
        """ Should the node be checked later? """
        # Can the bot stand here?
        if not world.has_collision(self.c_add(0, -1, 0)): return False
        # check air blocks above self when going down and horizontally
        for dy in range(max(2, self.parent.coords[1] - self.coords[1] + 2)):
            if world.has_collision(self.c_add(0, dy, 0)): return False
        # check air blocks above parent when going up
        for dy in range(self.coords[1] - self.parent.coords[1]):
            if world.has_collision(self.parent.c_add(0, dy+2, 0)): return False
        return True

    def is_unvisited(self, n_visited):
        """ Should the node be checked later? """
        for node in n_visited:
            if self.coords == node.coords:
                # this node must be worse than the old one,
                # because main loop checks node with shortest path first
                return False
        return True

    def try_add_neighbors(self, world, n_visited, n_open, finish_coords):
        """ Tries to add all adjacent blocks. """
        # TODO add larger numbers for climbing/dropping from higher
        # bot takes no fall damage and can move 100 blocks down at once
        # bot can only go up 2 blocks when also going sideways
        # should be the opposite number, so the bot can take the same path back
        for y in range(-2, 2+1): # +1 because range is exclusive
            for x, z in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                new_node = AStarNode(self.c_add(x, y, z), self, finish_coords)
                if new_node.is_valid(world) and new_node.is_unvisited(n_visited):
                    for node in n_open:
                        if new_node.coords == node.coords:
                            # node exists, do not create new one
                            if new_node.prev_dist < node.prev_dist:
                                # this node is better, replace old one
                                node.prev_dist = new_node.prev_dist
                                node.parent = new_node.parent
                                # coords and estim_dist are the same
                            break
                    else: # this node is not already being checked
                        n_open.append(new_node)

    def better_than(self, other):
        """ Returns True if this node has the smallest total distance when travelling via it. """
        if self.prev_dist + self.estim_dist == other.prev_dist + other.estim_dist:
            return self.prev_dist < other.prev_dist # better in foresight, usually estimation is too low
        return self.prev_dist + self.estim_dist < other.prev_dist + other.estim_dist

def astar(c_from, c_to, world):
    """ Finds a shortest path between two coordinates in a world.
    If there is a path, returns a list of all coordinates that lie on the path.
    Otherwise, returns an empty list."""
    # swap from/to, A* finds a path from finish to start
    start_coords, finish_coords = tuple(block_coords(c_to)), tuple(block_coords(c_from))
    start = AStarNode(start_coords, None, finish_coords)
    finish = AStarNode(finish_coords, None, finish_coords)
    n_open = [start]
    n_visited = []
    print 'start:', start, 'finish:', finish

    for tries in range(100):
        # find node with shortest path
        best_i = len(n_open)-1
        best_n = n_open[-1]
        for i, iter_n in enumerate(n_open[:-1]):
            if iter_n.better_than(best_n):
                best_i = i
                best_n = iter_n
        #print 'Nodes:', n_open
        node = n_open.pop(best_i)
        n_visited.append(node)
        #print 'Best:', node
        # Are we done?
        if node.coords == finish.coords:
            break
        # not done, check neighbors
        node.try_add_neighbors(world, n_visited, n_open, finish_coords)
        if len(n_open) <= 0:
            print '[A*] No path found, all accessible nodes checked,', tries+1 #, 'in total:'
            #print n_visited
            return []
    else:
        print '[A*] Took too long to find path, increase tries in astar.py'
        return []
    print '[A*] Found path after', tries+1, 'steps'

    path = []
    # build path by backtracing from finish to start, i.e. from -> to
    path.append(node.coords)
    while node.parent is not None: # TODO test for zero-length paths (from == to)
        node = node.parent
        path.append(node.coords)
    return path


if __name__ == '__main__':
    class WorldTest:
        def has_collision(self, x, y, z, what):
            if x == 0 and y == 0:
                return True
            return False
    world = WorldTest()
    print 'Got path', astar((0, 1, 0), (0, 1, 2), world)