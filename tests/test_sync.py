import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dashboard as sync
import build_dashboard as builder

GUID = '0123456789abcdef'
SONG = 'Songs/Pop/Example/'

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.profile = self.data/'profiles'/GUID
        (self.profile/'events').mkdir(parents=True)
        (self.profile/'songs').mkdir()
        self.stats = '''<Stats><GeneralData><Guid>0123456789abcdef</Guid><DisplayName>Player</DisplayName><IsMachine>0</IsMachine><NumTotalSongsPlayed>1</NumTotalSongsPlayed></GeneralData><SongScores><Song Dir="Songs/Pop/Example/"><Steps StepsType="dance-single" Difficulty="Hard"><HighScoreList><NumTimesPlayed>1</NumTimesPlayed><LastPlayed>2026-11-12</LastPlayed><HighScore><DateTime>2026-11-12 12:00:00</DateTime><Grade>Tier01</Grade><PercentDP>0.99</PercentDP><Score>100</Score></HighScore></HighScoreList></Steps></Song></SongScores></Stats>'''
        (self.profile/'Stats.xml').write_text(self.stats)
        (self.profile/'manifest.json').write_text(json.dumps({'version':1, 'profile_guid':GUID, 'profile_kind':'local', 'event_count':1}))
        self.event('play-1')
        self.meta = {'dir':SONG, 'title':'Example あ', 'artist':'Artist', 'charts':[{'stepstype':'dance-single','diff':'Hard','meter':9,'radar':{'taps':100}}], 'banner':''}
        self.save_meta()
    def tearDown(self):
        self.temp.cleanup()
    def save_meta(self):
        (self.profile/'songs'/(hashlib.sha256(SONG.encode()).hexdigest()+'.json')).write_text(json.dumps(self.meta))
    def event(self, guid, who=GUID):
        root = ET.fromstring(self.stats)
        node = ET.Element('HighScoreForASongAndSteps')
        ET.SubElement(node, 'Song', {'Dir':SONG})
        ET.SubElement(node, 'Steps', {'StepsType':'dance-single','Difficulty':'Hard'})
        score = copy.deepcopy(root.find('.//HighScore'))
        ET.SubElement(score, 'Guid').text = guid
        ET.SubElement(score, 'PlayerGuid').text = who
        node.append(score)
        result = ET.Element('Stats'); ET.SubElement(result,'RecentSongScores').append(node)
        path = self.profile/'events'/(hashlib.sha256(guid.encode()).hexdigest()+'.xml')
        ET.ElementTree(result).write(path)
        return path
    def build(self, name='site', baseline=None):
        return sync.build(self.data,GUID,self.root/name,baseline,'abc123')
    def test_import_retry_and_unicode(self):
        first = self.build()
        second = self.build('site2',self.root/'site')
        for obj in (first,second):
            self.assertEqual(obj['totals']['songsPlayed'],1)
            self.assertEqual(obj['recordedPlays'],1)
            self.assertEqual(len(obj['songs'][0]['charts'][0]['scores']),1)
            self.assertEqual(obj['songs'][0]['song'],'Example あ')

    def test_out_of_range_chart_meter_keeps_history_and_banner(self):
        self.meta['charts'][0]['meter'] = 144821752
        self.meta['banner'] = self.make_banner('red')
        self.save_meta()
        data = self.build()
        song = data['songs'][0]
        hard = song['charts'][0]
        self.assertIsNone(hard['meter'])
        self.assertEqual((hard['diff'], hard['radar']), ('Hard', {'taps': 100}))
        self.assertEqual((data['recordedPlays'], hard['plays']), (1, 1))
        self.assertEqual([(s['dt'], s['sc'], s['pct']) for s in hard['scores']],
                         [('2026-11-12 12:00:00', 100, 0.99)])
        self.assertEqual(song['banner'], self.meta['banner'])
        self.assertTrue((self.root/'site'/song['banner']).is_file())

    def test_out_of_range_chart_meter_uses_valid_published_rating(self):
        self.meta['charts'][0]['meter'] = 1000
        self.save_meta()
        self.build()
        for value in (1001, -1):
            with self.subTest(value=value):
                self.meta['charts'][0]['meter'] = value
                self.save_meta()
                current = self.build('retry', self.root/'site')
                self.assertEqual(current['songs'][0]['charts'][0]['meter'], 1000)

    def test_out_of_range_legacy_meter_is_not_restored(self):
        published = self.build()
        published['songs'][0]['charts'][0]['meter'] = 144821752
        (self.root/'site'/'data.json').write_text(json.dumps(published))
        next((self.profile/'songs').glob('*.json')).unlink()
        current = self.build('retry', self.root/'site')
        self.assertIsNone(current['songs'][0]['charts'][0]['meter'])

    def test_invalid_meter_type_still_rejects_the_export(self):
        for value in ('9', False, 9.5, None):
            with self.subTest(value=value):
                self.meta['charts'][0]['meter'] = value
                self.save_meta()
                with self.assertRaisesRegex(ValueError, 'integer chart meter.*Example'):
                    self.build()

    def test_distinct_guids_same_timestamp_are_separate(self):
        self.event('play-2')
        data = self.build()
        self.assertEqual(data['recordedPlays'],2)
        self.assertEqual(len(data['songs'][0]['charts'][0]['scores']),2)
    def test_wrong_profile_rejected(self):
        self.event('play-1','ffffffffffffffff')
        with self.assertRaisesRegex(ValueError,'another profile'): self.build()
    def test_missing_old_logs_rejected(self):
        self.build()
        for p in (self.profile/'events').glob('*'): p.unlink()
        (self.profile/'manifest.json').write_text(json.dumps({'version':1,'profile_guid':GUID,'profile_kind':'local','event_count':0}))
        with self.assertRaisesRegex(ValueError,'Historical'): self.build('new', self.root/'site')
    def test_total_regression_rejected(self):
        self.build()
        (self.profile/'Stats.xml').write_text(self.stats.replace('<NumTotalSongsPlayed>1','<NumTotalSongsPlayed>0'))
        with self.assertRaisesRegex(ValueError,'total decreased'): self.build('new',self.root/'site')
    def test_private_fields_and_entities_rejected(self):
        (self.profile/'Stats.xml').write_text(self.stats.replace('<GeneralData>','<GeneralData><Secret>token</Secret>'))
        with self.assertRaisesRegex(ValueError,'Unexpected'): self.build()
        (self.profile/'Stats.xml').write_text('<!DOCTYPE Stats>'+self.stats)
        with self.assertRaisesRegex(ValueError,'XML declarations'): self.build()
    def test_traversal_symlinks_and_event_names_rejected(self):
        self.meta['dir']='Songs/../../secret';self.save_meta()
        with self.assertRaisesRegex(ValueError,'directory'): self.build()
        self.meta['dir']=SONG;self.save_meta()
        (self.data/'link').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError,'Symlinks'): self.build()
        (self.data/'link').unlink()
        self.event('play-1').rename(self.profile/'events'/'wrong.xml')
        with self.assertRaisesRegex(ValueError,'filename'): self.build()
    def test_theme_calibration_in_snapshot_preserves_totals(self):
        self.build()
        for theme in ('default', '_fallback', 'Chiikawa'):
            with self.subTest(theme=theme):
                root = ET.fromstring(self.stats)
                root.find('GeneralData/NumTotalSongsPlayed').text = '4'
                calibration = copy.deepcopy(root.find('SongScores/Song'))
                calibration.set('Dir', f'Themes/{theme}/Other/')
                calibration.find('.//NumTimesPlayed').text = '3'
                root.find('SongScores').append(calibration)
                ET.ElementTree(root).write(self.profile/'Stats.xml')
                result = self.build('with-calibration', self.root/'site')
                self.assertEqual(result['totals']['songsPlayed'], 4)
                self.assertEqual(result['recordedPlays'], 1)
                self.assertEqual([s['dir'] for s in result['songs']], [SONG])

    def test_theme_calibration_cannot_bypass_path_validation(self):
        for directory in ('Themes/../Other/', 'Themes/default/Other/../../Save/',
                          'Themes/default/Other/./', 'Themes/default//Other/',
                          '/Themes/default/Other/', 'Themes/default/Other\\secret/',
                          'Themes/default/Graphics/', 'Save/LocalProfiles/',
                          'Songs/../Save/', 'Songs/./Example/'):
            with self.subTest(directory=directory):
                (self.profile/'Stats.xml').write_text(self.stats.replace(SONG, directory))
                with self.assertRaisesRegex(ValueError, 'directory'):
                    self.build()

    def test_theme_directory_only_allowed_in_snapshot(self):
        theme_dir = 'Themes/default/Other/'
        event = self.event('play-1')
        original = event.read_text()
        event.write_text(original.replace(SONG, theme_dir))
        with self.assertRaisesRegex(ValueError, 'directory'):
            self.build()
        event.write_text(original)
        self.meta['dir'] = theme_dir
        self.save_meta()
        with self.assertRaisesRegex(ValueError, 'directory'):
            self.build()

    def test_history_error_explains_omitted_logs(self):
        current = self.build()
        previous = copy.deepcopy(current)
        previous['recordedPlays'] = 5918
        current['recordedPlays'] = 827
        # This also looks like a per-song regression; report the missing logs first.
        previous['songs'][0]['plays'] = 2
        with self.assertRaisesRegex(ValueError, '827 uploaded, 5918 already published.*skipped_other_profiles'):
            sync.verify_history(previous, current)

    def test_new_logs_cannot_hide_missing_older_days(self):
        previous = self.build()
        current = copy.deepcopy(previous)
        current['recordedPlays'] += 1
        current['playsDaily'] = [['2026-11-13', 2]]
        with self.assertRaisesRegex(ValueError, 'incomplete for 2026-11-12'):
            sync.verify_history(previous, current)

    def test_song_history_is_still_checked_with_complete_logs(self):
        previous = self.build()
        current = copy.deepcopy(previous)
        current['songs'][0]['plays'] = 0
        with self.assertRaisesRegex(ValueError, 'Historical song plays'):
            sync.verify_history(previous, current)

    def make_banner(self, color):
        image = io.BytesIO()
        builder.Image.new("RGB", (80, 20), color).save(image, format="PNG")
        raw = image.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        (self.data/"banners").mkdir(exist_ok=True)
        (self.data/"banners"/(digest + ".json")).write_text(json.dumps({"png_base64": base64.b64encode(raw).decode()}))
        return "banners/" + digest + ".png"

    def save_pack(self, directory, banner):
        target = self.profile/"packs"/(hashlib.sha256(directory.encode()).hexdigest() + ".json")
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps({"dir": directory, "banner": banner}))
        return target

    def test_pack_fills_missing_history_and_song_art_takes_priority(self):
        song_art = self.make_banner("red")
        pack_art = self.make_banner("blue")
        pack = "Songs/Pop/"
        self.save_pack(pack, pack_art)
        # Old clients may never have uploaded any metadata for this song.
        next((self.profile/"songs").glob("*.json")).unlink()
        data = self.build()
        for row in (data["songs"][0], data["recent"][0]):
            self.assertEqual((row["banner"], row["bannerSource"]), (pack_art, "pack"))
        self.assertTrue((self.root/"site"/pack_art).is_file())
        self.assertEqual(json.loads((self.root/"site/data.json").read_text())["songs"][0]["bannerSource"], "pack")
        changed = self.make_banner("green")
        self.save_pack(pack, changed)
        self.assertEqual(self.build("new_pack", self.root/"site")["songs"][0]["banner"], changed)
        self.meta["banner"] = song_art
        self.save_meta()
        row = self.build("new_song", self.root/"new_pack")["songs"][0]
        self.assertEqual(row["banner"], song_art)
        self.assertNotIn("bannerSource", row)
        self.meta["banner"] = ""
        self.save_meta()
        row = self.build("archived", self.root/"new_song")["songs"][0]
        self.assertEqual(row["banner"], song_art)
        self.assertTrue((self.root/"archived"/song_art).is_file())

    def test_additional_library_pack_is_distinct(self):
        other = SONG.replace("Songs/", "AdditionalSongs/")
        (self.profile/"Stats.xml").write_text(self.stats.replace(SONG, other))
        event = next((self.profile/"events").glob("*"))
        event.write_text(event.read_text().replace(SONG, other))
        self.save_pack("Songs/Pop/", self.make_banner("red"))
        expected = self.make_banner("blue")
        self.save_pack("AdditionalSongs/Pop/", expected)
        data = self.build()
        self.assertEqual((data["songs"][0]["pack"], data["songs"][0]["banner"]), ("Pop", expected))
        self.assertEqual(data["recent"][0]["banner"], expected)

    def test_pack_record_is_bound_to_exact_directory(self):
        name = self.make_banner("red")
        record = self.save_pack("Songs/Pop/", name)
        for directory in ("Songs/Elsewhere/", "Songs/Pop/Other/", "Songs/../"):
            record.write_text(json.dumps({"dir": directory, "banner": name}))
            with self.assertRaisesRegex(ValueError, "directory"):
                self.build()
        self.save_pack("Songs/Pop/", "../other.png")
        with self.assertRaisesRegex(ValueError, "banner name"):
            self.build()

    def test_banner_envelope_and_historical_retention(self):
        raw = io.BytesIO();builder.Image.new('RGB',(80,20),'pink').save(raw,'PNG');png=raw.getvalue()
        digest = hashlib.sha256(png).hexdigest()
        (self.data/'banners').mkdir()
        (self.data/'banners'/(digest+'.json')).write_text(json.dumps({'png_base64':base64.b64encode(png).decode()}))
        self.meta['banner']='banners/'+digest+'.png'; self.save_meta()
        data=self.build();self.assertEqual((self.root/'site'/self.meta['banner']).read_bytes(),png)
        self.meta['banner']='';self.save_meta()
        data=self.build('new',self.root/'site');self.assertTrue(data['songs'][0]['banner'])
        self.assertEqual((self.root/'new'/data['songs'][0]['banner']).read_bytes(),png)
    def test_duplicate_upload_file_legacy_builder(self):
        src=self.event('play-1');(self.profile/'events'/'copy.xml').write_bytes(src.read_bytes())
        parsed=builder.parse_uploads(str(self.profile/'events'),lambda d:{'title':'','artist':''})
        self.assertEqual(parsed['recordedPlays'],1)

    def test_live_attempt_counter_rollback_keeps_published_count(self):
        root = ET.fromstring(self.stats)
        root.find('.//NumTimesPlayed').text = '3'
        root.find('.//LastPlayed').text = '2026-11-13'
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        first = self.build()
        (self.profile/'Stats.xml').write_text(self.stats)
        current = self.build('restored', self.root/'site')
        self.assertEqual(current['recordedPlays'], 1)
        song = current['songs'][0]
        self.assertEqual(song['plays'], 3)
        self.assertEqual(song['diffs'], {'Hard': 3})
        self.assertEqual(song['charts'][0]['plays'], 3)
        self.assertEqual(song['last'], '2026-11-13')
        self.assertEqual(len(song['charts'][0]['scores']), 1)
        self.assertEqual(current['packs'][0]['plays'], 3)
        self.assertEqual(current['artists'][0]['plays'], 3)
        status = json.loads((self.root/'restored/sync-status.json').read_text())
        self.assertEqual(status['history_retention']['chart_counters'][0]['uploaded'], 1)
        self.assertEqual(status['history_retention']['chart_counters'][0]['retained'], 3)
        self.assertEqual((self.profile/'Stats.xml').read_text(), self.stats)

    def test_trimmed_profile_score_survives_repeated_publications(self):
        root = ET.fromstring(self.stats)
        root.find('GeneralData/NumTotalSongsPlayed').text = '2'
        root.find('.//NumTimesPlayed').text = '2'
        score = copy.deepcopy(root.find('.//HighScore'))
        score.find('DateTime').text = '2026-11-11 12:00:00'
        score.find('PercentDP').text = '0.5'
        root.find('.//HighScoreList').append(score)
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        first = self.build()
        root.find('.//HighScoreList').remove(score)
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        second = self.build('restored', self.root/'site')
        third = self.build('retry', self.root/'restored')
        self.assertEqual(first['songs'], second['songs'])
        self.assertEqual(second['songs'], third['songs'])
        self.assertEqual(second['recordedPlays'], 1)
        status = json.loads((self.root/'restored/sync-status.json').read_text())
        self.assertEqual(status['history_retention']['score_records'], 1)
        # Each fresh build restores the one absent input record; output stays identical.
        self.assertEqual(json.loads((self.root/'retry/sync-status.json').read_text())['history_retention']['score_records'], 1)

    def test_same_day_replacement_cannot_hide_missing_known_event(self):
        old = self.event('older-event')
        tree = ET.parse(old)
        tree.find('.//DateTime').text = '2026-11-12 13:00:00'
        tree.write(old)
        self.build()
        old.unlink()
        new = self.event('replacement-event')
        tree = ET.parse(new)
        tree.find('.//DateTime').text = '2026-11-12 14:00:00'
        tree.write(new)
        with self.assertRaisesRegex(ValueError, 'Historical play event is missing: older-event'):
            self.build('replacement', self.root/'site')
        self.assertFalse((self.root/'replacement/sync-status.json').exists())

    def test_altered_known_event_is_rejected(self):
        old = self.event('older-event')
        tree = ET.parse(old)
        tree.find('.//DateTime').text = '2026-11-12 13:00:00'
        tree.write(old)
        self.build()
        tree.find('.//Score').text = '99'
        tree.write(old)
        with self.assertRaisesRegex(ValueError, 'Historical play event changed: older-event'):
            self.build('changed', self.root/'site')

    def test_retention_cannot_recreate_a_missing_chart(self):
        root = ET.fromstring(self.stats)
        extra = copy.deepcopy(root.find('.//Steps'))
        extra.set('Difficulty', 'Medium')
        root.find('.//Song').append(extra)
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        self.build()
        (self.profile/'Stats.xml').write_text(self.stats)
        with self.assertRaisesRegex(ValueError, 'Historical chart is missing.*Medium'):
            self.build('missing-chart', self.root/'site')

    def test_retention_cannot_recreate_a_missing_song(self):
        self.build()
        root = ET.fromstring(self.stats)
        root.find('SongScores').remove(root.find('SongScores/Song'))
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        with self.assertRaisesRegex(ValueError, 'Historical song is missing'):
            self.build('missing-song', self.root/'site')

    def test_intact_duplicate_edit_charts_do_not_need_recovery(self):
        root = ET.fromstring(self.stats)
        song = root.find('.//Song')
        for count in (1, 2, 2):
            extra = copy.deepcopy(root.find('.//Steps'))
            extra.set('Difficulty', 'Edit')
            extra.find('HighScoreList/NumTimesPlayed').text = str(count)
            extra.find('HighScoreList').remove(extra.find('HighScoreList/HighScore'))
            song.append(extra)
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        first = self.build()
        current = self.build('retry', self.root/'site')
        self.assertEqual(first['songs'], current['songs'])
        root.findall('.//Steps')[-1].find('HighScoreList/NumTimesPlayed').text = '1'
        ET.ElementTree(root).write(self.profile/'Stats.xml')
        with self.assertRaisesRegex(ValueError, 'ambiguous historical charts'):
            self.build('ambiguous', self.root/'site')

if __name__ == '__main__': unittest.main()
