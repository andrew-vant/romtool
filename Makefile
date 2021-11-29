.PHONY : all wheel venv clean test

version = $(shell python3 setup.py --version)
wheel = romtool-$(version)-py2-none-any.whl
deb = romtool_$(version)_all.deb

all : wheel
wheel : dist/$(wheel)

dist/$(wheel) :
	python3 setup.py bdist_wheel

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
