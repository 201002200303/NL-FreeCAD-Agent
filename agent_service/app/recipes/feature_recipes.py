from app.recipes.registry import get_recipe


def box_with_fillet_recipe() -> dict:
    return get_recipe("box_with_fillet_recipe")


def hole_cut_recipe() -> dict:
    return get_recipe("hole_cut_recipe")

