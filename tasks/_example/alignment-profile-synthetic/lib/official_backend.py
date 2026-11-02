"""Load a server-prepared real packet without numeric runtime dependencies."""


def load_official_profile(packet_path):
    from core import load_packet, ContractError
    packet = load_packet(packet_path)
    if packet['synthetic_only'] is not False:
        raise ContractError('expected real data; synthetic fallback is forbidden')
    return packet
