import os
import glob
import shutil

for f in glob.glob("migration_*.sql"):
    new_name = f.replace("migration_", "")
    new_path = os.path.join("migrations", new_name)
    shutil.move(f, new_path)
    print(f"Moved {f} to {new_path}")
