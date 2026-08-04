from app.recipes.registry import get_recipe


def boolean_cut_recipe() -> dict:
    return get_recipe("boolean_cut_recipe")

