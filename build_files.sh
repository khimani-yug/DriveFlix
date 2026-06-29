# build_files.sh
echo "Building project..."
python3 -m pip install -r requirements.txt --break-system-packages
python3 manage.py collectstatic --noinput --clear
python3 manage.py migrate --noinput
echo "Build complete."
