import subprocess
import sys

def run_script(script_name):
    try:
        result = subprocess.run([sys.executable, script_name], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Successfully executed {script_name}:\n{result.stdout.decode()}")
    except subprocess.CalledProcessError as e:
        print(f"Error executing {script_name}:\n{e.stderr.decode()}")

def main():
    # Run the scripts in the desired order
    print("Starting setup process...")
    run_script("tablecreating.py")
    run_script("iteminserting.py")
    run_script("gettingcurrentprice.py")
    print("Setup process completed.")

if __name__ == "__main__":
    main()
