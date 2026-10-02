import os
import sys
import re
import json
import pypdf

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

UPLOAD_DIR = r'C:\Users\parshwanath\.gemini\antigravity-ide\brain\ac36d04f-1762-407d-b9cc-54908055a49d\.user_uploaded'

# Canonical station names mapping
CANONICAL_NAMES = {
    'BGM': 'BELAGAVI CBT',
    'CBT': 'BELAGAVI CBT',
    'BELAGAVI': 'BELAGAVI CBT',
    'BELGAUM': 'BELAGAVI CBT',
    'CKD': 'CHIKKODI',
    'CHIKODI': 'CHIKKODI',
    'CHIKKODI': 'CHIKKODI',
    'ATN': 'ATHANI',
    'ATHANI': 'ATHANI',
    'ATHANNI': 'ATHANI',
    'NPN': 'NIPPANI',
    'NIPANI': 'NIPPANI',
    'NIPPANI': 'NIPPANI',
    'SNK': 'SANKESHWAR',
    'SANKESHWAR': 'SANKESHWAR',
    'SANKESWAR': 'SANKESHWAR',
    'RBG': 'RAIBAG',
    'RAIBAG': 'RAIBAG',
    'RAYBAG': 'RAIBAG',
    'MRJ': 'MIRAJ',
    'MIRAJ': 'MIRAJ',
    'VJP': 'VIJAYAPURA',
    'VJPR': 'VIJAYAPURA',
    'VIJAYAPUR': 'VIJAYAPURA',
    'VIJAYAPURA': 'VIJAYAPURA',
    'KLP': 'KOLHAPUR',
    'KOLAPUR': 'KOLHAPUR',
    'KOLHAPUR': 'KOLHAPUR',
    'HBL': 'HUBBALLI',
    'HUBBALLI': 'HUBBALLI',
    'HUBLI': 'HUBBALLI',
    'DWR': 'DHARWAD',
    'DHARWAD': 'DHARWAD',
    'DHARAWAD': 'DHARWAD',
    'DARAWAD': 'DHARWAD',
    'ICL': 'ICHALKARANJI',
    'ICHALKARANJI': 'ICHALKARANJI',
    'ICHALKANRAJI': 'ICHALKARANJI',
    'ICHALAKARANJI': 'ICHALKARANJI',
    'INCHALKARANJI': 'ICHALKARANJI',
    'SNGL': 'SANGLI',
    'SANGLI': 'SANGLI',
    'SANGALI': 'SANGLI',
    'BLR': 'BENGALURU',
    'BNG': 'BENGALURU',
    'BENGALURU': 'BENGALURU',
    'BANGLORE': 'BENGALURU',
    'MYS': 'MYSURU',
    'MYSORE': 'MYSURU',
    'KLB': 'KALABURAGI',
    'KLBG': 'KALABURAGI',
    'KALABURGI': 'KALABURAGI',
    'KALABURAGI': 'KALABURAGI',
    'GLB': 'KALABURAGI',
    'SLP': 'SOLAPUR',
    'SOLLAPUR': 'SOLAPUR',
    'SOLAPUR': 'SOLAPUR',
    'BLH': 'BAILHONGAL',
    'BAILHONGAL': 'BAILHONGAL',
    'KNP': 'KHANAPUR',
    'KHANAPUR': 'KHANAPUR',
    'GMK': 'GOKAK',
    'GOKAK': 'GOKAK',
    'SDG': 'SADALAGA',
    'SADALAGA': 'SADALAGA',
    'HUK': 'HUKKERI',
    'HUKKERI': 'HUKKERI',
    'IND': 'INDI',
    'INDI': 'INDI',
    'MDL': 'MUDHOL',
    'MUDHOL': 'MUDHOL',
    'GLD': 'GULEDGUDDA',
    'GULEDGUDDA': 'GULEDGUDDA',
    'VDM': 'BADAMI',
    'BADAMI': 'BADAMI',
    'MHL': 'MAHALINGPUR',
    'MAHALINGPUR': 'MAHALINGPUR',
    'KMT': 'KUMTA',
    'KUMTA': 'KUMTA',
    'RCH': 'RAICHUR',
    'RAICHUR': 'RAICHUR',
    'BGK': 'BAGALKOT',
    'BAGALKOT': 'BAGALKOT',
    'YDGR': 'YADGIR',
    'YADAGIR': 'YADGIR',
    'KUSTAGI': 'KUSHTAGI',
    'KUSHTAGI': 'KUSHTAGI',
    'SHAHAPUR': 'SHAHAPUR',
    'SHAPUR': 'SHAHAPUR',
    'SINDAGI': 'SINDAGI',
    'MUDDEBIHAL': 'MUDDEBIHAL',
    'MBL': 'MUDDEBIHAL',
    'JEVARGI': 'JEVARGI',
    'SHIVAMOGGA': 'SHIVAMOGGA',
    'SHIVAMOGA': 'SHIVAMOGGA',
    'SHAVAMOGA': 'SHIVAMOGGA',
    'SMG': 'SHIVAMOGGA',
    'KARWAR': 'KARWAR',
    'DANDELI': 'DANDELI',
    'LONDA': 'LONDA',
    'PANJIM': 'PANJIM',
    'PANAJI': 'PANJIM',
    'VASCO': 'VASCO',
    'MADAGAON': 'MADAGAON',
    'MAPUSA': 'MAPUSA',
    'PUNE': 'PUNE',
    'MUMBAI': 'MUMBAI',
    'BORIVALI': 'MUMBAI',
    'NASIK': 'NASHIK',
    'JAMAKHANDI': 'JAMAKHANDI',
    'JAMKHANDI': 'JAMKHANDI',
    'RATNAGIRI': 'RATNAGIRI',
    'SAUNDATTI': 'SAUNDATTI',
    'RAMDURG': 'RAMDURG',
    'BALLARY': 'BALLARI',
    'BELLARY': 'BALLARI',
    'BIDAR': 'BIDAR',
    'HUMANABAD': 'HUMANABAD',
    'CHITRADURGA': 'CHITRADURGA',
    'CHITRADURD': 'CHITRADURGA',
    'SURAPUR': 'SURAPUR',
    'SGL': 'SAVALAGI',
    'PRAL': 'PARAMANANDAWADI',
    'NDND': 'NANDANI',
    'INC': 'INCHAL',
}

# Coordinate table for known stations/towns/villages across Belagavi Division & borders
COORDS = {
    'BELAGAVI CBT': (74.5065, 15.8573),
    'CHIKKODI': (74.5960, 16.4300),
    'ATHANI': (75.0592, 16.7328),
    'NIPPANI': (74.3807, 16.4026),
    'SANKESHWAR': (74.4780, 16.2580),
    'RAIBAG': (74.7780, 16.4880),
    'LONDA': (74.5152, 15.4497),
    'GOKAK': (74.8236, 16.1685),
    'KHANAPUR': (74.5147, 15.6385),
    'BAILHONGAL': (74.8569, 15.8155),
    'SAUNDATTI': (75.1167, 15.7656),
    'RAMDURG': (75.2970, 15.9480),
    'HUKKERI': (74.6010, 16.2280),
    'SADALAGA': (74.5350, 16.5720),
    'MIRAJ': (74.6465, 16.7725),
    'SANGLI': (74.5815, 16.8524),
    'ICHALKARANJI': (74.4620, 16.6920),
    'KOLHAPUR': (74.2433, 16.7050),
    'VIJAYAPURA': (75.7175, 16.8288),
    'HUBBALLI': (75.1240, 15.3647),
    'DHARWAD': (75.0078, 15.4589),
    'BENGALURU': (77.5946, 12.9716),
    'MYSURU': (76.6394, 12.2958),
    'KALABURAGI': (76.8343, 17.3297),
    'SOLAPUR': (75.9064, 17.6599),
    'BAGALKOT': (75.6980, 16.1850),
    'BADAMI': (75.6766, 15.9189),
    'MUDHOL': (75.2864, 16.3353),
    'GULEDGUDDA': (75.7869, 16.0506),
    'MAHALINGPUR': (75.1147, 16.3980),
    'JAMAKHANDI': (75.2941, 16.5113),
    'INDI': (75.9592, 17.1784),
    'SINDAGI': (76.2347, 16.9206),
    'MUDDEBIHAL': (76.1340, 16.3340),
    'SHAHAPUR': (76.8420, 16.7010),
    'YADGIR': (77.1350, 16.7700),
    'KUSHTAGI': (76.1950, 15.7580),
    'BALLARI': (76.9214, 15.1394),
    'BIDAR': (77.5190, 17.9104),
    'HUMANABAD': (77.2960, 17.8280),
    'CHITRADURGA': (76.4020, 14.2250),
    'SHIVAMOGGA': (75.5681, 13.9299),
    'KARWAR': (74.1306, 14.8136),
    'KUMTA': (74.4070, 14.4260),
    'DANDELI': (74.6229, 15.2427),
    'PANJIM': (73.8325, 15.4989),
    'VASCO': (73.8117, 15.3982),
    'MADAGAON': (73.9580, 15.2736),
    'MAPUSA': (73.8150, 15.5920),
    'PUNE': (73.8567, 18.5204),
    'MUMBAI': (72.8777, 19.0760),
    'NASHIK': (73.7898, 19.9975),
    'RATNAGIRI': (73.3000, 16.9940),
    'RAICHUR': (77.3556, 16.2120),
    # Belagavi City / Suburban hubs
    'ANGOL': (74.5120, 15.8310),
    'VADAGAON': (74.4980, 15.8340),
    'KANBARGI': (74.5380, 15.8820),
    'MUCHANDI': (74.5820, 15.9230),
    'SULEBHAVI': (74.6540, 15.8920),
    'VANTUMRI': (74.5240, 15.9320),
    'RAMTRITH NGR': (74.5380, 15.8760),
    'H BASTWAD': (74.5210, 15.7890),
    'YELLUR': (74.4980, 15.7820),
    'SULAGA': (74.4680, 15.9120),
    'MAJAGAON': (74.5020, 15.8210),
    'DHAMNE': (74.4550, 15.8640),
    'CHANDAGAD': (74.1800, 15.9300),
    'BASRIKATTI': (74.4800, 15.8900),
    'KAKATI': (74.5300, 15.9300),
    'PEERANWADI': (74.4600, 15.8200),
    'SAMBRA': (74.6100, 15.8600),
    # Rural Stops & Taluks
    'KHADAKALAT': (74.4750, 16.4850),
    'GALATAGA': (74.4500, 16.5100),
    'KARADAGA': (74.4800, 16.5400),
    'BHOJ': (74.4300, 16.5600),
    'MANGUR': (74.4400, 16.5900),
    'EXAMBA': (74.5100, 16.5900),
    'BENNALI': (74.5400, 16.5000),
    'BAMBALWAD': (74.5500, 16.5200),
    'MUGALKOD': (75.0500, 16.4600),
    'YADUR': (74.6900, 16.6100),
    'DIGGEWADI': (74.6200, 16.4800),
    'CHANDUR': (74.6600, 16.5200),
    'HARUGERI': (74.9600, 16.5400),
    'KUDACHI': (74.8520, 16.6340),
    'SHIRGUPPI': (74.7725, 16.6342),
    'KADAPUR': (74.6800, 16.4200),
    'JODAKURLI': (74.6400, 16.3800),
    'KERUR': (74.7200, 16.3200),
    'KALLOL': (74.6300, 16.6100),
    'NARSINHWADI': (74.6900, 16.6900),
    'SAVALAGI': (75.1800, 16.5200),
    'HIDKAL DAM': (74.6400, 16.1500),
    'APACHIWADI': (74.3200, 16.3500),
    'JATRAT': (74.3400, 16.3900),
    'GADINGLAJ': (74.3500, 16.2300),
    'HALIYAL': (74.7600, 15.3300),
}

def clean_time(t):
    if not t: return '08:00'
    t = re.sub(r'^[^\d]+', '', t.strip())
    t = re.sub(r'[^\d\.\:]+$', '', t)
    t = t.replace(';', ':').replace('.', ':')
    parts = t.split(':')
    if len(parts) >= 2:
        try:
            h = int(parts[0]) % 24
            m = int(parts[1]) % 60
            return f'{str(h).zfill(2)}:{str(m).zfill(2)}'
        except:
            return '08:00'
    return '08:00'

def canonical(name):
    norm = name.strip().upper()
    norm = re.sub(r'[\.\-\/\_]+', ' ', norm).strip()
    return CANONICAL_NAMES.get(norm, norm)

def get_lat_lng(name):
    c = canonical(name)
    if c in COORDS:
        return COORDS[c]
    # Check partials
    for k, v in COORDS.items():
        if k in c or c in k:
            return v
    # Centroid around Belagavi district
    return (74.5065, 15.8573)

all_schedules = []

# 1. LONDA
print("Parsing LONDA...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316456373.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 8:
            all_schedules.append({
                'id': f'lnd-{parts[0]}',
                'source_terminal': 'LONDA BUS STAND',
                'division': parts[1],
                'depot': parts[2],
                'sch_no': parts[3],
                'from': canonical(parts[4]),
                'to': canonical(parts[5]),
                'platform_no': parts[6],
                'arrl': clean_time(parts[7]),
                'dept': clean_time(parts[8]) if len(parts) > 8 else clean_time(parts[7]),
                'service_type': 'Vegadhoot' if 'EXP' in line.upper() else 'Ordinary',
                'category': 'Inter-District'
            })

# 2. CBT CITY & SUBURBAN
print("Parsing CBT CITY & SUBURBAN...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316622518.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 8:
            all_schedules.append({
                'id': f'cbt-city-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'BELAGAVI CBT',
                'division': 'Belagavi',
                'depot': parts[2] if len(parts) > 2 else 'BGV-2',
                'sch_no': parts[3] if len(parts) > 3 else '1',
                'from': canonical(parts[4]),
                'to': canonical(parts[5]),
                'platform_no': parts[6] if len(parts) > 6 else '1',
                'arrl': clean_time(parts[7]) if len(parts) > 7 else '08:00',
                'dept': clean_time(parts[8]) if len(parts) > 8 else '08:05',
                'service_type': 'Ordinary',
                'category': 'City & Suburban'
            })

# 3. RAIBAG
print("Parsing RAIBAG...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316622550.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 7:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            service = 'Vegadhoot' if any(x in line.upper() for x in ['EXPRESS', 'EXP']) else 'Ordinary'
            from_stn = canonical(parts[4]) if len(parts) > 4 else 'RAIBAG'
            to_stn = canonical(parts[5]) if len(parts) > 5 else 'BELAGAVI CBT'
            plat = parts[6] if len(parts) > 6 and parts[6].isdigit() else '2'
            all_schedules.append({
                'id': f'rbg-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'RAIBAG BUS STAND',
                'division': parts[1] if len(parts) > 1 else 'Chikkodi',
                'depot': 'RAIBAG',
                'sch_no': parts[2] if len(parts) > 2 else '1',
                'from': from_stn,
                'to': to_stn,
                'platform_no': plat,
                'arrl': arrl,
                'dept': dept,
                'service_type': service,
                'category': 'Inter-Taluk'
            })

# 4. SANKESHWAR
print("Parsing SANKESHWAR...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316622596.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 7:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            service = 'Vegadhoot' if 'EXPRESS' in line.upper() else 'Ordinary'
            plat = parts[-4] if len(parts) >= 8 and parts[-4].isdigit() else '3'
            from_stn = canonical(parts[3]) if len(parts) > 3 else 'SANKESHWAR'
            to_stn = canonical(parts[4]) if len(parts) > 4 else 'BELAGAVI CBT'
            all_schedules.append({
                'id': f'snk-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'SANKESHWAR BUS STAND',
                'division': 'Chikkodi',
                'depot': parts[1] if len(parts) > 1 else 'Sankeshwar',
                'sch_no': parts[2] if len(parts) > 2 else '1',
                'from': from_stn,
                'to': to_stn,
                'platform_no': plat,
                'arrl': arrl,
                'dept': dept,
                'service_type': service,
                'category': 'Inter-Taluk'
            })

# 5. NIPPANI
print("Parsing NIPPANI...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316622680.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 6:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            plat = parts[-3] if len(parts) >= 7 and parts[-3].isdigit() else '7'
            to_stn = canonical(parts[-4]) if len(parts) >= 8 else 'BELAGAVI CBT'
            from_stn = canonical(parts[-5]) if len(parts) >= 9 else 'NIPPANI'
            all_schedules.append({
                'id': f'npn-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'NIPPANI BUS STAND',
                'division': 'Chikkodi',
                'depot': parts[1] if len(parts) > 1 else 'Nippani',
                'sch_no': parts[2] if len(parts) > 2 else '1',
                'from': from_stn,
                'to': to_stn,
                'platform_no': plat,
                'arrl': arrl,
                'dept': dept,
                'service_type': 'Vegadhoot' if 'EXP' in line.upper() else 'Ordinary',
                'category': 'Inter-Taluk'
            })

# 6. CBT EXPRESS & LONG DISTANCE
print("Parsing CBT EXPRESS...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789316622735.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 7:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            plat = parts[-3] if len(parts) >= 8 and parts[-3].isdigit() else '1'
            to_stn = canonical(parts[-4]) if len(parts) >= 8 else 'BENGALURU'
            from_stn = canonical(parts[-5]) if len(parts) >= 9 else 'BELAGAVI CBT'
            svc = 'Airavat Club Class' if any(x in line.upper() for x in ['AIRAVAT', 'VOLVO']) else ('Rajahamsa' if 'RAJAHAMSA' in line.upper() else 'Vegadhoot')
            all_schedules.append({
                'id': f'cbt-exp-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'BELAGAVI CBT',
                'division': parts[1] if len(parts) > 1 else 'Belagavi',
                'depot': parts[2] if len(parts) > 2 else 'Belagavi-1',
                'sch_no': parts[3] if len(parts) > 3 else '1',
                'from': from_stn,
                'to': to_stn,
                'platform_no': plat,
                'arrl': arrl,
                'dept': dept,
                'service_type': svc,
                'category': 'Express & Long Distance'
            })

# 7. ATHANI
print("Parsing ATHANI...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789317536958.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 8:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            plat = parts[-3] if parts[-3].isdigit() else '2'
            to_stn = canonical(parts[-4])
            from_stn = canonical(parts[-5])
            all_schedules.append({
                'id': f'atn-{parts[0]}-{len(all_schedules)}',
                'source_terminal': 'ATHANI BUS STAND',
                'division': parts[1] if len(parts) > 1 else 'Chikodi',
                'depot': parts[2] if len(parts) > 2 else 'ATHANI',
                'sch_no': parts[3] if len(parts) > 3 else '1',
                'from': from_stn,
                'to': to_stn,
                'platform_no': plat,
                'arrl': arrl,
                'dept': dept,
                'service_type': 'Vegadhoot' if any(x in line.upper() for x in ['EXP', 'EXPRESS']) else 'Ordinary',
                'category': 'Inter-Taluk'
            })

# 8. CHIKODI
print("Parsing CHIKODI...")
reader = pypdf.PdfReader(os.path.join(UPLOAD_DIR, 'media_1789317537078.pdf'))
for p in reader.pages:
    for line in (p.extract_text() or '').split('\n'):
        parts = line.strip().split()
        if parts and parts[0].isdigit() and len(parts) >= 8:
            dept = clean_time(parts[-1])
            arrl = clean_time(parts[-2])
            plat = parts[-3] if parts[-3].isdigit() else '9'
            rem = parts[1:-3]
            service = 'Ordinary'
            if rem and rem[-1].upper() in ['EXP', 'EXPRESS']:
                service = 'Vegadhoot'
                rem = rem[:-1]
            elif rem and rem[-1].upper() in ['ORD', 'ORDINARY']:
                service = 'Ordinary'
                rem = rem[:-1]
            if len(rem) >= 2:
                to_stn = canonical(rem[-1])
                from_stn = canonical(rem[-2])
                sch = rem[-3] if len(rem) >= 3 else '1'
                depot = rem[-4] if len(rem) >= 4 else 'CKD'
                div = rem[-5] if len(rem) >= 5 else 'CKD'
                all_schedules.append({
                    'id': f'ckd-{parts[0]}-{len(all_schedules)}',
                    'source_terminal': 'CHIKKODI BUS STAND',
                    'division': div,
                    'depot': depot,
                    'sch_no': sch,
                    'from': from_stn,
                    'to': to_stn,
                    'platform_no': plat,
                    'arrl': arrl,
                    'dept': dept,
                    'service_type': service,
                    'category': 'Inter-Taluk'
                })

print(f"\n==========================================")
print(f"TOTAL SCHEDULED OPERATIONS PARSED: {len(all_schedules)}")
print(f"==========================================")

# Extract all distinct station names
unique_stations = set()
for s in all_schedules:
    if s['from']: unique_stations.add(s['from'])
    if s['to']: unique_stations.add(s['to'])

print(f"Total Unique Stations Found: {len(unique_stations)}")

# Save to json files in src/server
os.makedirs(r'd:\Projects-For-Hustle\CBT_PROJECT\src\server\generated', exist_ok=True)
with open(r'd:\Projects-For-Hustle\CBT_PROJECT\src\server\generated\master_schedules.json', 'w', encoding='utf-8') as f:
    json.dump(all_schedules, f, indent=2)

station_list = []
for idx, stn in enumerate(sorted(unique_stations)):
    lng, lat = get_lat_lng(stn)
    station_list.append({
        'id': f'stn-{idx+1}',
        'name': stn,
        'platform_name': f'Bus Stand / Platform',
        'location': {
            'type': 'Point',
            'coordinates': [lng, lat]
        },
        'geofence_radius_meters': 60,
        'created_at': '2026-09-13T00:00:00.000Z'
    })

with open(r'd:\Projects-For-Hustle\CBT_PROJECT\src\server\generated\master_stations.json', 'w', encoding='utf-8') as f:
    json.dump(station_list, f, indent=2)

print("Saved master_schedules.json and master_stations.json successfully!")
