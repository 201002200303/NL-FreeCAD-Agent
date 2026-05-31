from app.recipes.registry import get_recipe


def primitive_box_recipe() -> dict:
    return get_recipe("primitive_box_recipe")


def primitive_cylinder_recipe() -> dict:
    return get_recipe("primitive_cylinder_recipe")

