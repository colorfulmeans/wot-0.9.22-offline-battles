#!/usr/bin/env python3
"""Join the 2015 replay measurements to the pinned roster, never by fuzzy name.

Inputs are the original workbook attached to HellQwer's 2015-09-24 research
and the en/ru poliroid vehicle-name indexes. The latter supplies identity only,
not modern prices or profitability. Unmeasured vehicles use a labelled median
of measured vehicles of the same premium status, tier and class; the nearest
tier is used only when that group is empty. No runtime network dependency.
"""
import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import statistics
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from bake_mastery_thresholds_0922 import read_client_roster, vehicle_class
from bake_mastery_thresholds_0922 import NATIONS, SCRIPTS_PACKAGE
from packed_xml import read_packed_xml
from vehicle_prices import children, element, read_price

SOURCE = 'https://forum.tanki.su/topic/1660148-%D0%BE-%D0%BA%D1%80%D0%B5%D0%B4%D0%B8%D1%82%D0%B0%D1%85/'
WORKBOOK = 'https://forum-mt-prod.lesta.ru/monthly_09_2015/post-12045944-0-61402200-1443131647.xlsx'
CLASSES = {'ЛТ': 'lightTank', 'СТ': 'mediumTank', 'ТТ': 'heavyTank',
           'ПТ': 'AT-SPG', 'САУ': 'SPG'}
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value).lower()
                   if c.isalnum())


def measurements(path):
    with zipfile.ZipFile(path) as archive:
        strings = [''.join(t.itertext()) for t in ET.fromstring(
            archive.read('xl/sharedStrings.xml'))]
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        for row in sheet.findall('.//m:sheetData/m:row', NS):
            cells = {}
            for cell in row:
                value = cell.find('m:v', NS)
                if value is not None:
                    raw = value.text
                    cells[re.sub(r'\d', '', cell.get('r'))] = (
                        strings[int(raw)] if cell.get('t') == 's' else raw)
            if cells.get('E') in (None, 'None') or cells.get('B') not in CLASSES:
                continue
            yield (int(row.get('r')), cells['A'], int(cells['C']),
                   CLASSES[cells['B']], int((Decimal(cells['E']) * 10000
                                            ).quantize(1, rounding=ROUND_HALF_UP)))


def bake(client, workbook, indexes):
    roster = read_client_roster(client)
    # VehicleType derives premium from list.xml's gold price. The raw tags
    # parsed by read_client_roster do not contain that derived tag.
    premium_ids = set()
    package_path = Path(client) / SCRIPTS_PACKAGE if Path(client).is_dir() else Path(client)
    with zipfile.ZipFile(package_path) as package:
        for nation_id, nation in enumerate(NATIONS):
            root = read_packed_xml(package.read('scripts/item_defs/vehicles/%s/list.xml' % nation))
            for unused_name, node in children(root):
                section = element(node)
                if section is None:
                    continue
                fields = dict(children(section))
                if 'id' not in fields:
                    continue
                price = read_price(section)
                if price and price[1] > 0:
                    premium_ids.add((int(fields['id'].value) << 8) | (nation_id << 4) | 1)
    identities = defaultdict(set)
    for index in indexes:
        body = json.loads(Path(index).read_text(encoding='utf8'))
        for row in body['data']['data']['vehicles']:
            intcd = int(row[0])
            pinned = roster.get(intcd)
            if not pinned or row[1].lower() != pinned[1].lower() or row[2] != pinned[0]:
                continue
            for label in row[5:7]:
                identities[normalized(label)].add(intcd)
    measured = {}
    for source_row, label, tier, klass, factor in measurements(workbook):
        candidates = [intcd for intcd in identities[normalized(label)]
                      if roster[intcd][2] == tier and
                      vehicle_class(roster[intcd][3]) == klass]
        if len(candidates) == 1:
            intcd = candidates[0]
            if intcd in measured and measured[intcd][0] != factor:
                raise ValueError('conflicting measurement: %s' % label)
            measured[intcd] = (factor, source_row)
    samples = defaultdict(list)
    for intcd, (factor, unused) in measured.items():
        unused_nation, unused_name, tier, tags = roster[intcd]
        samples[(intcd in premium_ids, tier, vehicle_class(tags))].append(factor)
    result = {}
    for intcd, (nation, name, tier, tags) in sorted(roster.items()):
        key = '%s:%s' % (nation, name)
        if intcd in measured:
            result[key] = measured[intcd]
            continue
        groups = [(abs(tier - level), values) for (premium, level, klass), values
                  in samples.items() if premium == (intcd in premium_ids) and
                  klass == vehicle_class(tags)]
        if not groups:
            raise ValueError('no measured cohort: %s' % key)
        distance = min(row[0] for row in groups)
        values = [factor for delta, group in groups if delta == distance for factor in group]
        result[key] = (int(statistics.median(values)), 0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True)
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--names', required=True, nargs='+')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    rows = bake(args.client, args.workbook, args.names)
    header = ('# -*- coding: utf-8 -*-\n"""2015 credit measurements joined to #1513.\n'
              'Generated by tools/bake_credit_coefficients_0922.py.\n'
              'Value: (coefficient in ten-thousandths, original workbook row).\n'
              'A zero row explicitly denotes an offline cohort estimate.\n"""\n'
              'SOURCE = %r\nWORKBOOK = %r\nMEASURED_VERSION = "0.9.9 (2015)"\n'
              'COEFFICIENTS = {\n') % (SOURCE, WORKBOOK)
    Path(args.out).write_text(header + ''.join('    %r: %r,\n' % (key, value)
        for key, value in sorted(rows.items())) + '}\n', encoding='utf8')
    roster = read_client_roster(args.client)
    with Path(args.out).open('a', encoding='utf8') as output:
        output.write('\n# Exact pinned tiers remain available after the last catalogue donor leaves.\nVEHICLE_TIERS = {\n')
        for unused_id, (nation, name, tier, unused_tags) in sorted(roster.items()):
            output.write('    %r: %d,\n' % ('%s:%s' % (nation, name), tier))
        output.write('}\n')
    print('Baked %d vehicles: %d measured, %d labelled cohort estimates' % (
        len(rows), sum(bool(value[1]) for value in rows.values()),
        sum(not value[1] for value in rows.values())))


if __name__ == '__main__':
    main()
