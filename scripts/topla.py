#!/usr/bin/env python3
"""
Dünyadaki camileri OpenStreetMap'ten toplar ve 1°×1° kare dosyalarına böler.

Kaynak: Geofabrik'in bölge bölge hazır OSM dosyaları (download.geofabrik.de).
Her bölge indirilir, osmium ile içinden "religion=muslim" olanlar ayıklanır, dosya silinir.
Kimseye sorgu gönderilmediği için yoğunluk/engelleme sorunu olmaz.

Biten bölgelerin sonuçları parca/ klasöründe tutulur (GitHub önbelleği ile çalışmalar arasında
saklanır); süre biterse sonraki çalışma kaldığı yerden devam eder. Bütün bölgeler bitince
t/ kareleri baştan yazılır.

Çıktı: t/<enlem>_<boylam>.json  = [[enlem, boylam, "ad", {"dil": "ad"}], ...]
       bilgi.json              = son güncelleme bilgisi
"""
import json, math, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(KOK, 't')
PARCA = os.path.join(KOK, 'parca')
UA = 'QiboraMosqueTiles/3.0 (+https://kubilay-max.github.io/qibora/; miswakapp@gmail.com)'
INDEKS = 'https://download.geofabrik.de/index-v1-nogeom.json'
DILLER = ['en','tr','ar','id','ms','bn','ur','hi','fa','ps','ckb','ku','az','uz','kk','ky','tk','tg','ru','sq','bs',
          'fr','de','es','pt','it','nl','ha','yo','sw','so','am','ml','ta','th','ja','ko']
# Başka bölgelerle çakışan toplu bölgeler (içerikleri zaten ülke/eyalet dosyalarında var)
ATLA = {'alps', 'britain-and-ireland', 'dach', 'us-midwest', 'us-northeast', 'us-pacific', 'us-south', 'us-west'}
AYNI_ANDA = 3
SURE_SINIRI = 300 * 60
BASLANGIC = time.time()
AY = time.strftime('%Y-%m')
kilit = threading.Lock()

def log(*a):
    with kilit:
        print(*a, flush=True)

def indir(url, hedef, deneme=4):
    for i in range(deneme):
        try:
            istek = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(istek, timeout=120) as y, open(hedef, 'wb') as f:
                shutil.copyfileobj(y, f, 4 << 20)
            return True
        except Exception as x:
            log(f'   indirme hatası ({i + 1}): {x}')
            time.sleep(15 * (i + 1))
    return False

def bolgeler():
    """Geofabrik dizininden yaprak bölgeler (alt bölgesi olmayanlar)"""
    with urllib.request.urlopen(urllib.request.Request(INDEKS, headers={'User-Agent': UA}), timeout=120) as y:
        j = json.load(y)
    ozellik = [f['properties'] for f in j['features']]
    ebeveynler = {p.get('parent') for p in ozellik if p.get('parent')}
    liste = []
    for p in ozellik:
        if p['id'] in ebeveynler or p['id'] in ATLA or not p.get('urls', {}).get('pbf'):
            continue
        liste.append((p['id'], p['urls']['pbf']))
    return sorted(liste)

def merkez(geo):
    """GeoJSON geometrisinin yaklaşık merkezi (dış halka köşelerinin ortalaması)"""
    t = geo.get('type')
    c = geo.get('coordinates')
    if t == 'Point':
        return c[1], c[0]
    if t == 'LineString':
        noktalar = c
    elif t == 'Polygon':
        noktalar = c[0]
    elif t == 'MultiPolygon':
        noktalar = max((p[0] for p in c), key=len)
    elif t == 'MultiLineString':
        noktalar = [n for parca in c for n in parca]
    else:
        return None
    if not noktalar:
        return None
    return sum(n[1] for n in noktalar) / len(noktalar), sum(n[0] for n in noktalar) / len(noktalar)

def bolge_isle(kimlik, url):
    hedef = os.path.join(PARCA, kimlik.replace('/', '_') + '.json')
    if os.path.exists(hedef):
        return kimlik, 'önbellekte'
    with tempfile.TemporaryDirectory() as d:
        pbf = os.path.join(d, 'b.osm.pbf')
        t0 = time.time()
        if not indir(url, pbf):
            return kimlik, None
        boyut = os.path.getsize(pbf) / 1e6
        suzulmus = os.path.join(d, 's.osm.pbf')
        cikti = os.path.join(d, 's.geojsonseq')
        try:
            subprocess.run(['osmium', 'tags-filter', pbf, 'nwr/religion=muslim', '-o', suzulmus, '--overwrite'],
                           check=True)
            os.remove(pbf)
            subprocess.run(['osmium', 'export', suzulmus, '-f', 'geojsonseq', '-o', cikti, '--overwrite',
                            '-a', 'type,id', '-x', 'print_record_separator=false'], check=True)
        except subprocess.CalledProcessError as x:
            log(f'   osmium hatası {kimlik}: {x}')
            return kimlik, None
        sonuc = {}
        with open(cikti, encoding='utf-8') as f:
            for satir in f:
                satir = satir.strip().lstrip('\x1e')
                if not satir:
                    continue
                o = json.loads(satir)
                t = o.get('properties', {})
                if t.get('amenity') != 'place_of_worship':
                    continue
                m = merkez(o.get('geometry') or {})
                if not m:
                    continue
                anahtar = f"{str(t.get('@type', 'x'))[0]}{t.get('@id', '')}"
                ad_dil = {dl: t[f'name:{dl}'] for dl in DILLER if t.get(f'name:{dl}')}
                k = [round(m[0], 5), round(m[1], 5), t.get('name') or '']
                if ad_dil:
                    k.append(ad_dil)
                sonuc[anahtar] = k
    gecici = hedef + '.tmp'
    with open(gecici, 'w', encoding='utf-8') as f:
        json.dump(sonuc, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(gecici, hedef)
    return kimlik, f'{len(sonuc)} cami, {boyut:.0f} MB, {time.time() - t0:.0f} sn'

def kareleri_yaz():
    hepsi = {}
    for f in os.listdir(PARCA):
        if f.endswith('.json'):
            with open(os.path.join(PARCA, f), encoding='utf-8') as d:
                hepsi.update(json.load(d))  # aynı cami iki bölgede varsa bir kez sayılır
    kareler = {}
    for k in hepsi.values():
        kareler.setdefault(f'{math.floor(k[0])}_{math.floor(k[1])}', []).append(k)
    if len(hepsi) < 50000:
        log(f'UYARI: yalnızca {len(hepsi)} cami bulundu; kareler yazılmadı (bir şeyler ters gitmiş olabilir).')
        return False
    os.makedirs(CIKTI, exist_ok=True)
    for f in os.listdir(CIKTI):
        if f.endswith('.json') and f[:-5] not in kareler:
            os.remove(os.path.join(CIKTI, f))
    for k, liste in kareler.items():
        liste.sort(key=lambda r: (r[0], r[1]))
        with open(os.path.join(CIKTI, k + '.json'), 'w', encoding='utf-8') as f:
            json.dump(liste, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(KOK, 'bilgi.json'), 'w') as f:
        json.dump({'guncelleme': time.strftime('%Y-%m-%d'), 'kaynak': 'geofabrik', 'tamam': True,
                   'cami': len(hepsi), 'kare': len(kareler)}, f, indent=1)
    log(f'Bitti: {len(hepsi)} cami, {len(kareler)} kare yazıldı.')
    return True

def main():
    b = os.path.join(KOK, 'bilgi.json')
    if os.path.exists(b) and not os.environ.get('ZORLA'):
        with open(b) as f:
            bilgi = json.load(f)
        if bilgi.get('tamam') and bilgi.get('guncelleme', '')[:7] == AY:
            log(f'Bu ay ({AY}) veri zaten tamam; çıkılıyor.')
            return
    os.makedirs(PARCA, exist_ok=True)
    liste = bolgeler()
    log(f'{len(liste)} bölge; {len(os.listdir(PARCA))} tanesi önbellekte.')
    eksik = 0
    with ThreadPoolExecutor(AYNI_ANDA) as havuz:
        isler = {}
        for kimlik, url in liste:
            isler[havuz.submit(lambda k=kimlik, u=url: bolge_isle(k, u) if time.time() - BASLANGIC < SURE_SINIRI else (k, 'süre'))] = kimlik
        for n, is_ in enumerate(as_completed(isler), 1):
            kimlik, durum = is_.result()
            if durum is None or durum == 'süre':
                eksik += 1
            log(f'[{n}/{len(liste)}] {kimlik}: {durum or "ALINAMADI"}')
    if eksik:
        log(f'{eksik} bölge eksik; sonraki çalışmada tamamlanacak.')
        sys.exit(0)
    kareleri_yaz()

if __name__ == '__main__':
    main()
