import json
import os

SWORD_PATTERNS = {
    "longsword": ["H  ",
                  " M ",
                  "  M"],
    "twinblade": ["  M",
                  " H ",
                  "M  "],
    "rapier": ["  M",
               " M ",
               "H  "],
    "katana": ["   ",
               "HMM",
               "   "],
    "sai": [" M ",
            "H  ",
            "   "],
    "spear": ["  M",
              " H ",
              "H  "],
    "glaive": ["  M",
               " HM",
               "H  "],
    "warglaive": ["   ",
                  " B ",
                  "MHM"],
    "cutlass": [" B ",
                "MM ",
                "H  "],
    "claymore": [" BM",
                 "BMB",
                 "HB "],
    "greathammer": ["MMM",
                    "BBB",
                    " H "],
    "greataxe": ["MMM",
                 "BHB",
                 " H "],
    "chakram": ["BMB",
                "M M",
                "BHB"],
    "scythe": ["MHM",
               "MH ",
               "H  "],
    "halberd": [" MB",
                "MHM",
                "H  "]
}

keys = {}

def create_key(prefix, namespace, identifier):
    keys[identifier] = [prefix, f"{namespace}:{identifier}"]


def create_key_data():
    # Minecraft and Common
    create_key("tag", "c", "wood_sticks")
    create_key("item", "minecraft", "iron_nugget")
    create_key("item", "minecraft", "blaze_rod")
    create_key("item", "minecraft", "blaze_powder")

    # Twilight Forest
    for item in ["fiery_ingot", "knightmetal_ingot", "ironwood_ingot", "steeleaf_ingot"]:
        create_key("item", "twilight_forest", item)

    # Deeper Darker
    create_key("item", "deeperdarker", "reinforced_echo_shard")

    # Souls Weapons
    create_key("item", "soulsweapons", "lost_soul")

    # Better End
    #TODO add

    # Better Nether
    #TODO add

    # Blue Skies
    for item in [
        "pyrope_gem", "aquite", "diopside_gem", "charoite", "horizonite_ingot",
        "turquoise_cobblestone", "lunar_cobblestone", "bluebright_planks",
        "lunar_planks", "starlit_planks", "dusk_planks", "frostbright_planks",
        "maple_planks", "comet_planks"
    ]:
        create_key("item", "blue_skies", item)

    # Undergarden
    for item in ["cloggrum_ingot", "froststeel_ingot", "utheric_shard", "forgotten_ingot"]:
        create_key("item", "undergarden", item)

def create_tier_data():

    # Twilight Forest
    create_tier("knightmetal", "twilight_forest", keys["knightmetal_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("fiery", "twilight_forest", keys["fiery_ingot"], keys["blaze_rod"], keys["blaze_powder"])
    create_tier("ironwood", "twilight_forest", keys["ironwood_ingot"], keys["wood_sticks"], keys["iron_nugget"])   
    create_tier("steeleaf", "twilight_forest", keys["steeleaf_ingot"], keys["wood_sticks"], keys["iron_nugget"])

    # Blue Skies
    create_tier("pyrope", "blue_skies", keys["pyrope_gem"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("aquite", "blue_skies", keys["aquite"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("diopside", "blue_skies", keys["diopside_gem"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("charoite", "blue_skies", keys["charoite"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("horizonite", "blue_skies", keys["horizonite_ingot"], keys["wood_sticks"], keys["iron_nugget"])

    create_tier("turquoise_stone", "blue_skies", keys["turquoise_cobblestone"], keys["wood_sticks"], keys["turquoise_cobblestone"])
    create_tier("lunar_stone", "blue_skies", keys["lunar_cobblestone"], keys["wood_sticks"], keys["lunar_cobblestone"])

    create_tier("bluebright_wood", "blue_skies", keys["bluebright_planks"], keys["wood_sticks"], keys["bluebright_planks"])
    create_tier("lunar_wood", "blue_skies", keys["lunar_planks"], keys["wood_sticks"], keys["lunar_planks"])
    create_tier("starlit_wood", "blue_skies", keys["starlit_planks"], keys["wood_sticks"], keys["starlit_planks"])
    create_tier("dusk_wood", "blue_skies", keys["dusk_planks"], keys["wood_sticks"], keys["dusk_planks"])
    create_tier("frostbright_wood", "blue_skies", keys["frostbright_planks"], keys["wood_sticks"], keys["frostbright_planks"])
    create_tier("maple_wood", "blue_skies", keys["maple_planks"], keys["wood_sticks"], keys["maple_planks"])
    create_tier("comet_wood", "blue_skies", keys["comet_planks"], keys["wood_sticks"], keys["comet_planks"])

    # Undergarden
    create_tier("cloggrum", "undergarden", keys["cloggrum_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("froststeel", "undergarden", keys["froststeel_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("utheric", "undergarden", keys["utheric_shard"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("forgotten", "undergarden", keys["forgotten_ingot"], keys["wood_sticks"], keys["iron_nugget"])

def create_tier(name, mod_id, material, handle, binder):
    for sword in SWORD_PATTERNS:
        create_shaped_recipe(sword, name, mod_id, material, handle, binder)

    #for sword in SWORD_SETS:
    #    create_shaped_recipe(sword, name, mod_id, material, handle, binder)

def get_loader_conditions(mod_id):
    if loader == "fabric":
        return "fabric:load_conditions", [{"condition": "fabric:all_mods_loaded", "values": [mod_id]}]
    elif loader == "forge":
        return "conditions", [{"type": "forge:mod_loaded", "modid": mod_id}]
    print("Loader not recognized or supported.")
    return None, []

def get_result_item(mod_id, name, sword):
    if mod_id == "blue_skies":
        return f"blue_skies:{name}/{sword}"
    return f"knavesneeds:{mod_id}/{name}/{sword}"

def create_shaped_recipe(sword, name, mod_id, material, handle, binder):
    pattern = SWORD_PATTERNS.get(sword, [])
    result = get_result_item(mod_id, name, sword)
    condition_type, conditions = get_loader_conditions(mod_id)

    recipe_keys = {
        "H": {str(handle[0]): str(handle[1])},
        "M": {str(material[0]): str(material[1])}
    }

    if any("B" in row for row in pattern):
        recipe_keys["B"] = {str(binder[0]): str(binder[1])}

    json_data = {
        condition_type: conditions,
        "type": "minecraft:crafting_shaped",
        "category": "equipment",
        "key": recipe_keys,
        "pattern": pattern,
        "result": {"item": result}
    }

    filename = f"data/recipes/{mod_id}/{name}/{sword}.json"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    loader = input("Fabric or Forge?")
    create_key_data()
    create_tier_data()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
