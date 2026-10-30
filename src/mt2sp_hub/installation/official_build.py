"""Public official-source fingerprints only; no game bytes or local observations.

Reproduce with tools/review_game_baseline.py. This reference does not authorize
activation or certify gameplay. See docs/GAME_BASELINE.md for provenance.
"""

PROFILE = {
    "client_version": "2.0.135",
    "files": {
        "client": {
            "D3DCompiler_43.dll": {
                "bytes": 2529176,
                "sha256": "ffedb064adc25328b24dcf145b04045a867a5574c931516d7845babf2a08937f"
            },
            "ILU.dll": {
                "bytes": 109568,
                "sha256": "f77f132281384f9067dee3baf4f4912009ddc6011a576f3ce5edb9e8a1532335"
            },
            "ILUT.dll": {
                "bytes": 36352,
                "sha256": "f72ce93c3a6ae4c1b7ed62a74c75636225efe7c0971823f010f8db5db18a3b37"
            },
            "MilesCompat64.dll": {
                "bytes": 1649152,
                "sha256": "697176f55f865d03d45c0aaaf81201d9f644b4684fd145e9092eeb5a8fe85816"
            },
            "SecureEngineSDK64.dll": {
                "bytes": 28672,
                "sha256": "175a75ca524b269b25fb5144dc0abb4ac9b1673852df3abfbd4f6c449e01827d"
            },
            "SpeedTreeRT.dll": {
                "bytes": 536576,
                "sha256": "8406542da2c03aba735fd11597eed280714a0d8fb1afa664da78195725f2437d"
            },
            "concrt140.dll": {
                "bytes": 324208,
                "sha256": "2405355f0a58067b258f8df33c327e3a3d716eaac5a3a5aebb757842d85bd376"
            },
            "d3dx9_43.dll": {
                "bytes": 2404248,
                "sha256": "36b84dfa0ef9d3ff3549a7ad54d2a8032bd22c879219ee1a959137c4ef8786c4"
            },
            "devil.dll": {
                "bytes": 1762304,
                "sha256": "ea839e2e9ccceedc35b772ab06284b34b370f7fa13d7ad0a76036106c13c4f7e"
            },
            "granny2.dll": {
                "bytes": 803328,
                "sha256": "5464ba0b84fa5960ff0b5712c85a72b1efbed3cc3d0bc351a2d7bd82c015fb57"
            },
            "metin2client.exe": {
                "bytes": 10889216,
                "sha256": "d07cd4aaf6857bc3ddd9199b6ae590c8268c4f9cb36da939525cf8f900f48721"
            },
            "msvcp140.dll": {
                "bytes": 557728,
                "sha256": "0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9"
            },
            "msvcp140_1.dll": {
                "bytes": 35952,
                "sha256": "bfad5aef4c63a669e3c140655cdfdf395b6c979b400a447bd5dcb65ed8826c3d"
            },
            "msvcp140_2.dll": {
                "bytes": 280200,
                "sha256": "3ea06f0ee098b4823cb79599df3780e7f23cce52c19aac31d2a0d47efe33a5e9"
            },
            "msvcp140_atomic_wait.dll": {
                "bytes": 50304,
                "sha256": "640b2aefced484d0368eea5bdd06addd0658a3a70a49256e560d6923b404a479"
            },
            "msvcp140_codecvt_ids.dll": {
                "bytes": 31872,
                "sha256": "f2069a52880ec885ee7f0511186100eb7fada0411a2b4948fafea7735b878a18"
            },
            "pack/root.data": {
                "bytes": 18677504,
                "sha256": "cdebaea9d055698bca0e2818a6da1fefe3bd2ffb9a80da265dd83bf9693142b2"
            },
            "pack/root.index": {
                "bytes": 37288,
                "sha256": "351f8b67bd41cc2d7331783339460110363c1046b1fbd271a397db6c7c27e729"
            },
            "pack/root.json": {
                "bytes": 641,
                "sha256": "1644a611038c52e408a7e6c841cd440c9759f086b9254682cd16753f54025f33"
            },
            "vccorlib140.dll": {
                "bytes": 352384,
                "sha256": "19839407c3fdbc824e5bce189bf68ddf8097f12ec28b757797ffa0415c144ddd"
            },
            "vcruntime140.dll": {
                "bytes": 124544,
                "sha256": "d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066"
            },
            "vcruntime140_1.dll": {
                "bytes": 49792,
                "sha256": "1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f"
            },
            "vcruntime140_threads.dll": {
                "bytes": 38528,
                "sha256": "219915cf20822f34d5e7c1fdd4e21ae7f3396881096c51036225fb8f84b47afa"
            }
        },
        "server": {
            "linux-port/docker/game/Dockerfile": {
                "bytes": 64602,
                "sha256": "b0da8b1361ecffdf0445e8f461f6d442831a287c3ebbd40b27e11c2da075e3c7"
            },
            "linux-port/docker/game/bin/db": {
                "bytes": 5556200,
                "sha256": "1fad44a926c5b5c15b812c8fbd84b0ca53b8fa1c1737a9fbaab3e6baf4007f39"
            },
            "linux-port/docker/game/bin/game": {
                "bytes": 18097096,
                "sha256": "5b3d2269d3401c4fe0492eaf879460707a1883efdc0c7618a2a0182a2b67a3b6"
            },
            "linux-port/docker/game/bin/qc": {
                "bytes": 281060,
                "sha256": "8f6746652ebeca1e4c0c983831f3e62bcfe7afbddff87968d45973edd4e9ec36"
            },
            "linux-port/docker/game/scripts/entrypoint.sh": {
                "bytes": 13507,
                "sha256": "ffb5422bd2d0c049b63eae29a5914d1a313e03f9fb75699dd5625f15b7114ce9"
            },
            "linux-port/docker/game/share/locale/poland/quest/quest_functions": {
                "bytes": 17054,
                "sha256": "fec277e7798c0c371710bafe0ccd23d47438315ba3a4686189fdd5fe99bc0c5a"
            }
        }
    },
    "id": "tieru-2.2.134",
    "server_trees": {
        "linux-port/docker/game": {
            "bytes": 60666041,
            "files": 14493,
            "sha256": "ce4c81d31a4981fac0ff50968b41483964dc3107b88444cd39e62cc9f362c850"
        }
    },
    "server_version": "2.2.134",
    "sources": {
        "base": {
            "bytes": 1025987160,
            "digest_source": "reviewed HTTPS download; not a publisher-signed checksum",
            "filename": "Metin2-Singleplayer-2.2.106-chroniony.zip",
            "linked_from": "https://metin2singleplayer.com/",
            "sha256": "f89ab4005d8346cf2a9114923cf25d8ab6554bca9275adac8f42b80e5ebf78ad",
            "url": "https://drive.google.com/file/d/1RuPolBqX6rP2nMzY-tHSgsEPgtaMJTkK/view"
        },
        "client": {
            "bytes": 136339998,
            "digest_source": "GitHub release asset digest",
            "sha256": "32b6ed5203cc98eb9adfd2a58cc5c9193f1f30a380c7fb5c62cc8de5735b0809",
            "url": "https://github.com/TieruYT/metin2-playerbots/releases/download/v2.2.134/metin2-client-update-2.0.135.zip"
        },
        "executable": {
            "bytes": 10889216,
            "digest_source": "GitHub release asset digest; also pinned by the official update manifest",
            "sha256": "d07cd4aaf6857bc3ddd9199b6ae590c8268c4f9cb36da939525cf8f900f48721",
            "url": "https://github.com/TieruYT/metin2-playerbots/releases/download/v2.2.126/metin2client.exe"
        },
        "server": {
            "bytes": 160270144,
            "digest_source": "GitHub release asset digest",
            "sha256": "e70bbeca45899aad502874b8f22e2c22e97be98255dabe241a31e39e20a70ef6",
            "url": "https://github.com/TieruYT/metin2-playerbots/releases/download/v2.2.134/metin2-server-protected-update-2.2.134.zip"
        },
        "supplement": {
            "bytes": 4060,
            "digest_source": "GitHub release asset digest",
            "sha256": "932fbd8839d1475a80fe03dbd4f772428c0e140161ab8df60ac77e6a2cad5e63",
            "url": "https://github.com/TieruYT/metin2-playerbots/releases/download/v2.2.134/metin2-client-update-2.0.135-supplement.zip"
        }
    }
}
