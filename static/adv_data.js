/* =========================================================================
   adv_data.js  --  reference tables for the Adventurer sheet
   =========================================================================
   Transcribed from the Dwarf Fortress wiki pages rather than written from
   memory, so the sheet matches what the game actually shows you.

     Skills / levels ... "Skill" and "Combat skill" pages (v53.16)
     Attributes ....... the 19 tracked attributes and their 9 rank names
     Calendar ......... 12 months x 28 days, 4 seasons

   Nothing here is generated or inferred. If DF adds a skill, this is the
   one place to add it.
   ========================================================================= */
(function(){
'use strict';

/* Skill levels. DF numbers Dabbling as 0 and Legendary as 15+; "Unskilled"
   is not a DF level at all. It's the "you have never touched this" state,
   added because a sheet listing 100 skills all at Dabbling is a lie about
   the character. df:null marks it as ours, not the game's. */
const SKILL_LEVELS = [
  {name:'Unskilled',    df:null},
  {name:'Dabbling',     df:0},
  {name:'Novice',       df:1},
  {name:'Adequate',     df:2},
  {name:'Competent',    df:3},
  {name:'Skilled',      df:4},
  {name:'Proficient',   df:5},
  {name:'Talented',     df:6},
  {name:'Adept',        df:7},
  {name:'Expert',       df:8},
  {name:'Professional', df:9},
  {name:'Accomplished', df:10},
  {name:'Great',        df:11},
  {name:'Master',       df:12},
  {name:'High Master',  df:13},
  {name:'Grand Master', df:14},
  {name:'Legendary',    df:15},
];

/* The full skill list, in the wiki's own groupings. Military and Social keep
   their sub-groups because that's how the game presents them. */
const SKILL_GROUPS = [
  ['Miner', ['Miner']],
  ['Woodworker', ['Bowyer','Carpenter','Wood cutter']],
  ['Stoneworker', ['Engraver','Stonecutter','Stone carver','Mason']],
  ['Ranger', ['Ambusher','Animal caretaker','Animal dissector','Animal trainer','Trapper']],
  ['Doctor', ['Bone doctor','Diagnostician','Surgeon','Suturer','Wound dresser']],
  ['Farmer', ['Beekeeper','Brewer','Butcher','Cheese maker','Cook','Dyer','Gelder','Planter',
              'Herbalist','Lye maker','Milker','Miller','Potash maker','Presser','Shearer',
              'Soaper','Spinner','Tanner','Thresher','Wood burner']],
  ['Fishery worker', ['Fish cleaner','Fish dissector','Fisherdwarf']],
  ['Metalsmith', ['Armorsmith','Furnace operator','Metal crafter','Blacksmith','Weaponsmith']],
  ['Jeweler', ['Gem cutter','Gem setter']],
  ['Craftsdwarf', ['Bookbinder','Bone carver','Clothier','Glassmaker','Glazer','Leatherworker',
                   'Papermaker','Potter','Stone crafter','Strand extractor','Wax worker',
                   'Weaver','Wood crafter']],
  ['Engineer', ['Mechanic','Pump operator','Siege engineer','Siege operator']],
  ['Administrator', ['Appraiser','Organizer','Record keeper']],
  ['Military. General', ['Archer','Armor user','Biter','Dodger','Fighter','Kicker',
                          'Shield user','Striker','Wrestler']],
  ['Military. Weapon', ['Axeman','Blowgunner','Bowman','Crossbowman','Hammerman','Knife user',
                         'Lasher','Maceman','Misc. object user','Pikeman','Spearman',
                         'Swordsman','Thrower']],
  ['Military. Other', ['Discipline','Leader','Military tactics','Observer','Student','Teacher']],
  ['Social. Broker', ['Comedian','Conversationalist','Flatterer','Intimidator','Judge of intent',
                       'Liar','Negotiator','Persuader']],
  ['Social. Other', ['Concentration','Consoler','Pacifier']],
  ['Performance. Music', ['Keyboardist','Musician','Percussionist','Singer',
                           'Stringed instrumentalist','Wind instrumentalist']],
  ['Performance. Spoken', ['Poet','Dancer','Speaker']],
  ['Scholar', ['Critical thinker','Logician','Mathematician','Astronomer','Chemist','Geographer',
               'Optics engineer','Fluid engineer','Wordsmith','Writer']],
  ['Other', ['Climber','Crutch-walker','Knapper','Reader','Rider','Schemer','Swimmer','Tracker']],
];

/* The 19 attributes DF tracks, split the way the game does. Physical first,
   then mental. */
const ATTRIBUTE_GROUPS = [
  ['Physical', ['Strength','Agility','Toughness','Endurance','Recuperation','Disease Resistance']],
  ['Mental', ['Analytical Ability','Focus','Willpower','Creativity','Intuition','Patience',
              'Memory','Linguistic Ability','Spatial Sense','Musicality','Kinesthetic Sense',
              'Empathy','Social Awareness']],
];

/* Best to worst. Index 4 ("(no description)")is the unremarkable middle
   and the sensible default: DF simply prints nothing for an average value.
   NOTE: Fortress mode's per-attribute idiomatic phrases ("unbelievably
   strong", "a sharp intellect", etc. See the wiki's Attribute page) are
   NOT what Adventure mode shows. The wiki says so explicitly: "These
   descriptions are not used in adventurer mode." Adventure mode's own
   character sheet instead shows one generic tier word next to the
   attribute's name ("High Strength", "Very High Agility")the same
   scale for every attribute, which is what this array reproduces. */
const ATTR_SCALE = [
  'Superior', 'Very High', 'High', 'Above Average', '(no description)',
  'Below Average', 'Low', 'Very Low', 'Abysmal',
];
const ATTR_DEFAULT = 4;

/* 12 months of 28 days, 4 seasons of 3 months. */
const MONTHS = [
  {n:1,  name:'Granite',   season:'Spring'},
  {n:2,  name:'Slate',     season:'Spring'},
  {n:3,  name:'Felsite',   season:'Spring'},
  {n:4,  name:'Hematite',  season:'Summer'},
  {n:5,  name:'Malachite', season:'Summer'},
  {n:6,  name:'Galena',    season:'Summer'},
  {n:7,  name:'Limestone', season:'Autumn'},
  {n:8,  name:'Sandstone', season:'Autumn'},
  {n:9,  name:'Timber',    season:'Autumn'},
  {n:10, name:'Moonstone', season:'Winter'},
  {n:11, name:'Opal',      season:'Winter'},
  {n:12, name:'Obsidian',  season:'Winter'},
];
const DAYS_IN_MONTH = 28;

/* Inventory categories. No authoritative wiki page for this one, so it's a
   practical set covering what an adventurer actually accumulates. Including
   things that aren't on your person, since a character ends up owning
   buildings and animals too. */
const ITEM_CATEGORIES = [
  'Weapon','Armor','Clothing','Shield','Ammunition','Tool','Instrument',
  'Food & drink','Container','Book or scroll','Gem or jewellery','Coins & wealth',
  'Trade good','Crafted item','Remains & trophy','Animal or mount',
  'Property or building','Claim or title','Miscellaneous',
];

/* Where a thing is, rather than whether it's worn, "worn vs carried" wasn't
   wanted, but "which of my three houses is it in" very much is. */
const ITEM_LOCATIONS = ['Carried','Stored','At a site','With a companion','Lost','Given away'];

const REPUTATION = [
  'Unknown','Hostile','Suspicious','Neutral','Friendly','Trusted','Loyal','Sworn',
  'Hero to them','Enemy to them',
];
const ASSOCIATE_KINDS = ['Acquaintance','Friend','Companion','Rival','Enemy','Patron',
                         'Quest giver','Family','Lover','Master','Apprentice','Deity'];
const QUEST_STATES = ['active','completed','failed'];
const CHAR_STATUS = ['Active','Retired','Deceased'];

window.ADV = {
  SKILL_LEVELS, SKILL_GROUPS, ATTRIBUTE_GROUPS, ATTR_SCALE, ATTR_DEFAULT,
  MONTHS, DAYS_IN_MONTH, ITEM_CATEGORIES, ITEM_LOCATIONS,
  REPUTATION, ASSOCIATE_KINDS, QUEST_STATES, CHAR_STATUS,
  ALL_SKILLS: SKILL_GROUPS.reduce((a,[,s])=>a.concat(s), []),
  ALL_ATTRIBUTES: ATTRIBUTE_GROUPS.reduce((a,[,s])=>a.concat(s), []),
};

})();
