.PHONY : all wheel nointro winpkg venv clean test ctags FORCE

# NOTE: Tabs for recipe indentation, spaces for logic indentation,
# because WHYYYYYYYYYYYYYYYY?!?!???

# Check whether we're on windows. Windows has a different python
# executable and a different default target.
ifdef OS
  # The version given here must match the one given in pynsist.in.cfg,
  # or things won't work. FIXME: find a way to single-source that. Also,
  # py.exe won't accept a patch version and I'm not sure what will
  # happen if it differs. Probably something bad.
  python = py.exe
  all = winpkg
  $(info windows detected ($$OS: $(OS)))
else
  python = python3
  all = wheel
endif

version = $(shell $(python) -W ignore setup.py --version)
wheel = romtool-$(version)-py2-none-any.whl
deb = romtool_$(version)_all.deb
nointro = src/romtool/nointro.tsv

all : $(all)
wheel : dist/$(wheel)
nointro : $(nointro)

dist/$(wheel) : $(nointro)
	pyproject-build

src/romtool/nointro.tsv : tools/dats.txt FORCE
	$(python) tools/rtbuild.py datomatic -v -f $< -o $@

# Build the windows executable installer. I haven't figured out how
# to make this work from a linux devbox yet, so this target must be
# run on Windows for the time being.
# NOTE: the default makefile shell on windows appears to be cmd.exe.
winpkg: pynsist.cfg $(nointro)
	-rmdir /Q /S .\build\wheels
	$(python) -m pip wheel -vw build\wheels .
	pynsist $<
	echo D | xcopy /y .\build\nsis\romtool_$(version).exe .\dist\

# Force is necessary because the recipe populates the current version,
# which may change even if the infile doesn't.
pynsist.cfg : pynsist.in.cfg FORCE
	py.exe tools/rtbuild.py nsis -vo $@ $<

deb :
	mkdir -p dist
	fpm \
		--force                                        \
		--name                        python3-romtool  \
		--input-type                  python           \
		--output-type                 deb              \
		--python-bin                  python3          \
		--python-package-name-prefix  python3          \
		--package                     dist/$(deb)      \
		setup.py
	ls -t dist/*.deb | head -n1 | xargs dpkg --info

lint :
	pylint src test
	pycodestyle src test

test :
	pytest-3 --cov src

ctags :
	ctags -Rf .tags .

cov :
	pytest-3 --cov src --cov-report term-missing

clean :
	-rm -rf build dist venv src/*.egg-info .tox
