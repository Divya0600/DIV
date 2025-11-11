Command-line options are of the form: –option value, where value may be
optional. Required arguments are in pointy brackets (< >) and optional
arguments are in brackets ([ ]). If the value must be from a list of possible
values, the available values are separated by |.
The basic form of the sfxcmd argument is: sfxcmd <projectname> [options]
where options are from the list below. By default, the project is rendered using
the settings in the project unless changed by command-line options. Rendering
can be disabled with the –render 0 option (see below). Certain options, such
as format conversion, will implicitly disable rendering as well.
-options <options file>
Load the options file and treat each line of the file as a command-line option.
For instance, instead of writing this:
sfxcmd project.sfx –log –info project
You can write this:
sfxcmd project.sfx –options options.txt
Where options.txt contains:
–log
–info project
Note: Lines that start with # in the options file will be ignored, so you can use # to add
comments.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 515
•
•
•
•
•
•
-version
Print the sfxcmd version.
-log
Enable log messages. For example, use –log to display module load
messages and other non-critical informational messages.
-info[project|session|node|render]
Print information about the overall project, the active session, active node or
active session rendering information. Enabling this option loads the info.py
script in the Silhouette scripts directory, and calls the appropriate function to
dump basic information. This file can be modified by the user to alter how the
information is presented. If just –info is used, the default is to display project
information. Multiple options can be supplied, separated by commas, to print
multiple types of information. For instance, –info session,render will print
session and rendering information. When –info is used, rendering is implicitly
disabled, unless the –render 1 option is also used.
The information displayed by –info can be customized by editing the info.py
Python script located in Silhouette/resources/scripts.
-session <name>
Make the specified session active in the project. This is only useful if the project
contains more than one session. To print a list of sessions in the project, use
the –info option.
-node <name>
Target the specified node in the active session for output. By default, the Output
node is used. The node name (ie. RotoNode, KeyerNode, etc) or the userdefined node label (as displayed in the node list) can be used. To print a list of
nodes in the active session, use the –info session option.
-no_launcher
Prevents the launcher from appearing when Silhouette starts up without a
project.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 516
•
•
•
•
•
•
-no_modules
Modules are prevented from loading.
-no_splash
Prevents the splash screen from appearing when Silhouette starts up.
-script <scriptfile>
Run the specified Python script after the project is loaded. The script has
access to the active project, session, and node, as specified by the –session
and –node options. Scripts can walk the object model, manipulate the object
state such as visibility, and print information, limited only by the Silhouette
scripting API.
-action <actionName>
Run the specified Action after the project is loaded, where actionName is an
action class name for one of the actions found in
Silhouette/resources/scripts/actions. When –action is used, rendering is
implicitly disabled, unless the –render 1 option is also used. Any rendering
done by the action itself is not disabled.
-render <0|1>
Rendering can be disabled by using –render 0. Use this if you only want to print
information about the project or run a script that does other things with the
project. Rendering is enabled by default if a project is specified.
Note that when –info or –action are used, –render 0 is implicitly set unless the
–render 1 option is also set.
Rendering options
-write <0|1>
Disable frame writing by using –write 0. This is useful for doing test runs to
verify that options are set properly.
-dir <path>
Specifies the output directory where files should be written to.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 517
•
•
•
•
•
•
-file <name>
Use –file to specify the root filename for output files.
-padding <number>
Sets the number of digits of padding for frame numbers. Use –padding 0 to
disable padding.
-range <all|work|start#-end#x#>
Specifies the range of frames to render. A specific range is set by passing two
numbers. A step factor can be introduced by using x# after the range. Some
examples are:
• –range 1-10 renders frames 1, 2, 3, 4, 5, 6, 7, 8, 9, and 10.
• –range 1-10x2 renders frames 1, 3, 5, 7, and 9.
• –range 3 renders frame 3.
Multiple –range arguments can be used to specify multiple ranges, for instance
–range 1-50x1 –range 51-60x2 –range 60-100x3. You can also use commas
to separate ranges in a single –range option.
Frames are in the range of the session, and do not necessarily start at 1. If your
session starts at frame 4000, to render the first 50 frames of the session, use –
range 4000-4049.
-f
Same as –range.
-step <number>
Specifies the number to add to get to the next frame. The default is 1. Note that
–step will override whatever step factor is used in –range or –f.
-start <number>
Use –start to override the starting frame number of the output frames. For
example, if your session starts at 4000 and you want to render 50 frames, but
you want the generated frame files to start at 1, use –range 4000-4049 –start
1.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 518
•
•
•
•
•
•
-depth <8|16|float>
Sets the render depth.
-save <rgba|rgb|alpha|paint>
Specifies the output type and the channels that are rendered. When using
RGBA, the –extalpha option can be used to write alpha to a separate file.
When using –save paint, a Paint Node is assumed to be present in the
session, and will be automatically targeted.
-crop <0|1>
Determines whether the crop region set in the Crop node is used.
-resolution <full|half|third|quarter>
Override the output resolution to full resolution, half resolution, third resolution,
quarter resolution.
Note: Half resolution is width/2*height/2, third resolution is width/3*height/3, and
quarter resolution is width/4*height/4.
-extalpha <0|1>
Use –extalpha 1 to write the alpha channel to a separate, single-channel file,
when supported by the file format. This is only useful when saving in RGBA
mode.
-mb <0|1>
Controls the motion blur on/off state of the targeted node providing that the
node supports motion blur. For instance, to force motion blur off in the Roto
node, you would write this: –node Roto –mb 0
-format <name>
Specifies the output file format. For a list of supported formats, consult the
format list in the Silhouette Render dialog.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 519
•
•
•
•
•
•
-formatopts <options>
Specifies format specific options for the output file format. The options are a
comma-separated list of name=value pairs. Consult the format options of the
desired file format in the Silhouette Render dialog. To view the current set of
format options, use the –info render option. For example, to set the SGI format
compression option to on, use –formatops compression=1.
-fields <none|interlace|aa|bb|bc|cd|dd>
Sets the field handling to one of the supported options. The two letter options
assume 3:2 handling.
-dominance <even|odd>
Sets the field dominance when field handling is enabled.
-view <left|right|both>
Sets the Stereo view(s) to render.
-domview <left|right>
Sets the dominant Stereo view when –view both is used.
-combinestereo <0|1> (available with EXR format only)
Enables writing of both Stereo views to the same file, with –view both when
the output format is EXR. The dominant view will be the first one referenced in
the file.
Note: -combinestereo is only available when using the EXR format.
-slapcomp <r,g,b,a>
Perform a slap comp on the rendered image when the output type is RGBA or
RGB. This will overlay the alpha channel over the RGB channels using the
color specified as 4 floating point numbers from 0-1. Use a negative alpha value
to invert the slap comp.
-nogui
For Linux systems without X-Windows installed, –nogui allows Silhouette to
not use X-Windows. However, scripts that do drawing, for example Slate, will
not work.
Silhouette User Guide
•
•
•
•
•
•
Command-Line 520
•
•
•
•
•
•
-threads
You can override the number of multi-processing threads Silhouette uses with
–threads <n>. 