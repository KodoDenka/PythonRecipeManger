import json
import os

global namespaces
global tiers
global keys
global sword_sets
global loader
sword_sets = ["chakram", "claymore", "cutlass", "glaive",
              "greataxe", "greathammer", "halberd", "katana",
              "longsword", "rapier", "sai", "scythe", "spear",
              "twinblade", "warglaive"]
keys = {}

def create_key_data():
    # Minecraft and Common
    create_key("tag", "c", "wood_sticks")
    create_key("item", "minecraft", "iron_nugget")
    create_key("item", "minecraft", "blaze_rod")

    # Twilight Forest
    create_key("item", "twilight_forest", "fiery_ingot")
    create_key("item", "twilight_forest", "knightmetal_ingot")
    create_key("item", "twilight_forest", "ironwood_ingot")
    create_key("item", "twilight_forest", "steeleaf_ingot")

    # Deeper Darker
    create_key("item", "deeperdarker", "reinforced_echo_shard")

    # Souls Weapons
    create_key("item", "soulsweapons", "lost_soul")

    # Better End
    #TODO add

    # Better Nether
    #TODO add

    # Blue Skies
    create_key("item", "blue_skies", "pyrope_gem")
    create_key("item", "blue_skies", "aquite")
    create_key("item", "blue_skies", "diopside_gem")
    create_key("item", "blue_skies", "charoite")
    create_key("item", "blue_skies", "horizonite_ingot")

    create_key("item", "blue_skies", "turquoise_cobblestone")
    create_key("item", "blue_skies", "lunar_cobblestone")

    create_key("item", "blue_skies", "bluebright_planks")
    create_key("item", "blue_skies", "lunar_planks")
    create_key("item", "blue_skies", "starlit_planks")
    create_key("item", "blue_skies", "dusk_planks")
    create_key("item", "blue_skies", "frostbright_planks")
    create_key("item", "blue_skies", "maple_planks")
    create_key("item", "blue_skies", "comet_planks")

    # Undergarden
    create_key("item", "undergarden", "cloggrum_ingot")
    create_key("item", "undergarden", "froststeel_ingot")
    create_key("item", "undergarden", "utheric_shard")
    create_key("item", "undergarden", "forgotten_ingot")

def create_tier_data():

    # Twilight Forest
    create_tier("knightmetal", "twilight_forest", keys["knightmetal_ingot"], keys["wood_sticks"], keys["iron_nugget"])
    create_tier("fiery", "twilight_forest", keys["fiery_ingot"], keys["blaze_rod"], keys["blaze_rod"])
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
    for sword in sword_sets:
        create_shaped_recipe(sword, name, mod_id, material, handle, binder)

def create_shaped_recipe(sword, name, mod_id, material, handle, binder):
    pattern = []

    match sword:
        case "longsword":
            pattern =  ["H  ",
                        " M ",
                        "  M"]
        case "twinblade":
            pattern =  ["  M",
                        " H ",
                        "M  "]
        case "rapier":
            pattern =  ["  M",
                        " M ",
                        "H  "]
        case "katana":
            pattern =  ["   ",
                        "HMM",
                        "   "]
        case "sai":
            pattern =  [" M ",
                        "H  ",
                        "   "]
        case "spear":
            pattern =  ["  M",
                        " H ",
                        "H  "]
        case "glaive":
            pattern =  ["  M",
                        " HM",
                        "H  "]
        case "warglaive":
            pattern = ["   ",
                       " B ",
                       "MHM"]
        case "cutlass":
            pattern = [" B ",
                       "MM ",
                       "H  "]
        case "claymore":
            pattern = [" BM",
                       "BMB",
                       "HB "]
        case "greathammer":
            pattern = ["MMM",
                       "BBB",
                       " H "]
        case "greataxe":
            pattern = ["MMM",
                       "BHB",
                       " H "]
        case "chakram":
            pattern = ["BMB",
                       "M M",
                       "BHB"]
        case "scythe":
            pattern = ["MHM",
                       "MH ",
                       "H  "]
        case "halberd":
            pattern = [" MB",
                       "MHM",
                       "H  "]

    result = "knavesneeds:" + mod_id + "/" + name + "/" + sword

    if loader == "fabric":
        condition_type = "fabric:load_conditions"
        conditions = [
    {
      "condition": "fabric:all_mods_loaded",
      "values": [
          mod_id
      ]
    }
  ]
    elif loader == "forge":
        condition_type = "conditions"
        conditions = [
    {
      "type": "forge:mod_loaded",
      "modid": mod_id
    }
]


    if any("B" in row for row in pattern):
        json_data = {
            condition_type: conditions,
            "type": "minecraft:crafting_shaped",
            "category": "equipment",
            "key": {
                "B": {str(binder[0]): str(binder[1])},
                "H": {str(handle[0]): str(handle[1])},
                "M": {str(material[0]): str(material[1])}
            },
            "pattern": pattern,
            "result": {"item": result}
        }

    else:
        json_data = {
            condition_type: conditions,
            "type": "minecraft:crafting_shaped",
            "category": "equipment",
            "key": {
                "H": {str(handle[0]): str(handle[1])},
                "M": {str(material[0]): str(material[1])}
            },
            "pattern": pattern,
            "result": {"item": result}
        }



    filename = "data/recipes/" + mod_id + "/" + name + "/" + sword + ".json"
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)


def create_key(prefix, namespace, identifier):
    keys[identifier] = [prefix, str(namespace + ":" + identifier)]


if __name__ == '__main__':
    loader = input("Fabric or Forge?")
    create_key_data()
    create_tier_data()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
