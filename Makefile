.PHONY : all wheel venv clean test

version = $(shell grep version setup.py | grep -oh '\".*\"' | cut -d '"' -f 2)
wheel = romtool-$(version)-py2-none-any.whl

all : wheel
wheel : dist/$(wheel)

dist/$(wheel) :
	python setup.py bdist_wheel

test :
	pytest-3 --cov src

cov :
	pytest-3 --cov src --cov-report term-missing

clean :
	-rm -rf build dist venv *.egg-info .tox
