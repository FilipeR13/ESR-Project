import sys, socket, threading, time
from ...utils.filereader import FileReader
from ...utils.messages import Messages_UDP
from ...utils.config import BOOTSTRAP_PORT, POINTS_OF_PRESENCE
from .topology import Topology
from typing import Dict, Tuple, List

class Bootstrap:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.topology = Topology()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('', BOOTSTRAP_PORT))
        
        self.read_file()

        self.thread_calculate_paths = threading.Thread(target=self.calculate_paths)
        self.stop_event = threading.Event()

    def read_file(self) -> None:
        file_reader = FileReader(self.file_path)
        file_contents = file_reader.read_json()
        if file_contents is not None:
            self.topology.add_nodes(file_contents)
            self.topology.display()
        else:
            sys.exit(1)

    def get_neighbours(self, ip: str) -> List[str]:
        return [neighbor['ip'] for neighbor in self.topology.get_neighbors(ip)]
        
    def send_interface(self, ip: str) -> None:
        interface = self.topology.get_primary_interface(ip)
        if interface is not None:
            print(f"New interface for {ip}: {interface}")
            Messages_UDP.send(self.socket, Messages_UDP.encode_json({'new_interface': interface}), ip, BOOTSTRAP_PORT)
        else:
            print(f"Unknown interface with IP {ip}")

    def calculate_paths(self) -> None:
        while not self.stop_event.is_set(): 
            recalculate_tree = False
            for pop in POINTS_OF_PRESENCE:
                path = self.topology.find_best_path(pop)
                if path != None:
                    distances, path = path
                    bool_new_path: bool = self.topology.store_path(pop, path, distances)
                    if bool_new_path:
                        recalculate_tree = True
                    print(f"Best path to {pop}: {path} with distance {distances}")
                else:
                    print(f"Could not find a path to {pop}")

            if recalculate_tree:
                self.build_tree()
            
            time.sleep(3)

    def build_tree(self) -> None:
        print("Building tree...")
        (tree, parents) = self.topology.build_tree()
        updated_parents = self.topology.update_tree(tree, parents)
        self.update_nodes(updated_parents)
        self.topology.display_tree()
    
    def update_nodes(self, updated_parents: List[Tuple[str,str]]) -> None:
        for node, parent in updated_parents:
            Messages_UDP.send(self.socket, Messages_UDP.encode_json({'parent': parent}), node, BOOTSTRAP_PORT)

    def update_topology(self, data: Dict, ip_node: str) -> None:
        for ip_neighbor, time in data.items():
            self.topology.update_velocity(ip_node, ip_neighbor, time)

    def send_initial_data(self, socket: socket.socket, ip_onode: int, onode_port: int) -> None:
        data = {}
        
        if self.topology.correct_interface(ip_onode):
            data["neighbours"] = self.get_neighbours(ip_onode)
        else:
            correct_interface = self.topology.get_primary_interface(ip_onode)
            data["new_interface"] = correct_interface
            data["neighbours"] = self.get_neighbours(correct_interface)

        Messages_UDP.send(socket, Messages_UDP.encode_json(data), ip_onode, onode_port)

    def receive_connections(self) -> None:
        try:
            while True:
                data, addr = self.socket.recvfrom(1024)
                if data != b'':
                    threading.Thread(target=self.update_topology, args=(Messages_UDP.decode_json(data), addr[0])).start()
                else:
                    threading.Thread(target=self.send_initial_data, args=(self.socket, addr[0], addr[1])).start()
        except KeyboardInterrupt:
            print("\nServer disconnected")
        finally:
            self.socket.close()
            self.stop_event.set()
            self.thread_calculate_paths.join()
            print("Socket closed.")
            sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 -m src.server.bootstrap.bootstrap <file_path>")
        sys.exit(1)
    
    bootstrap = Bootstrap(sys.argv[1])
    bootstrap.build_tree()
    bootstrap.thread_calculate_paths.start()
    bootstrap.receive_connections()