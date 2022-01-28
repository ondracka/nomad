#!/bin/sh
python -m nomad.cli dev metainfo > gui/src/metainfo.json
python -m nomad.cli dev search-quantities > gui/src/searchQuantities.json
python -m nomad.cli dev toolkit-metadata > gui/src/toolkitMetadata.json
python -m nomad.cli dev units > gui/src/unitsData.js
python -m nomad.cli dev parser-metadata > gui/src/parserMetadata.json