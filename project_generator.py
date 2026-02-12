import os
import json
import logging

class ProjectGenerator:
    def __init__(self):
        # We can store templates here if needed
        pass

    def generate_project(self, plan: dict, target_dir: str):
        """
        Generates the folder structure and basic files for the project based on the plan.
        """
        logging.info(f"Generating project '{plan.get('title')}' in {target_dir}")
        
        try:
            # 1. Create Root Directory
            os.makedirs(target_dir, exist_ok=True)

            # 2. Create project.json
            project_file = os.path.join(target_dir, "project.json")
            if not os.path.exists(project_file):
                project_data = {
                    "name": plan.get("title", "New Project"),
                    "version": "0.1.0",
                    "phases": plan.get("phases", [])
                }
                with open(project_file, 'w') as f:
                    json.dump(project_data, f, indent=4)

            # 3. Create README.md
            readme_file = os.path.join(target_dir, "README.md")
            if not os.path.exists(readme_file):
                with open(readme_file, 'w') as f:
                    f.write(f"# {plan.get('title')}\n\n")
                    f.write("## Plan\n")
                    for phase in plan.get("phases", []):
                        f.write(f"### {phase.get('name')}\n")
                        for task in phase.get("tasks", []):
                            f.write(f"- [ ] {task}\n")

            # 4. Create Source Folders (scaffolding)
            # Standard scaffold for now
            folders = ["src", "docs", "assets"]
            for folder in folders:
                os.makedirs(os.path.join(target_dir, folder), exist_ok=True)

            return True, "Project generated successfully."

        except Exception as e:
            logging.error(f"Project generation failed: {e}")
            return False, str(e)

project_generator = ProjectGenerator()
