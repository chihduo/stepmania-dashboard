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

if __name__ == '__main__': unittest.main()
