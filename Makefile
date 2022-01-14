.PHONY : all wheel winpkg venv clean test FORCE

version = $(shell python3 setup.py --version)
wheel = romtool-$(version)-py2-none-any.whl
deb = romtool_$(version)_all.deb

all : wheel
wheel : dist/$(wheel)
nointro : src/romtool/nointro.tsv

dist/$(wheel) : $(nointro)
	python3 setup.py bdist_wheel

src/romtool/nointro.tsv : tools/dats.txt FORCE
	python3 tools/rtbuild.py datomatic -v -f $< -o $@

winpkg: pynsist.cfg
	# Build the windows executable installer. I haven't figured out how
	# to make this work from a linux devbox yet, so this target must be
	# run on Windows for the time being. The Python version supplied to
	# py.exe must be installed, and must match the version in
	# pynsist.in.cfg. TODO: find a way to single-source that.
	rm -rf build/wheels
	py.exe -3.10.1 -m pip wheel -vw build/wheels .
	pynsist $<

pynsist.cfg : pynsist.in.cfg
	py.exe tools/rtbuild.py nsis -vo $@ $<

deb :
	mkdir -p dist
	fpm \
		-f \
		-n python3-romtool \
		-s python \
		-t deb \
		--python-bin python3 \
		--python-package-name-prefix python3 \
		-p dist/$(deb) \
		setup.py
	ls -t dist/*.deb | head -n1 | xargs dpkg --info

test :
	pytest-3 --cov src

cov :
	pytest-3 --cov src --cov-report term-missing

clean :
	-rm -rf build dist venv src/*.egg-info .tox
