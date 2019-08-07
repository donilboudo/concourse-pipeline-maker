import os, shutil, errno, copy
import yaml
import logging
import tempfile
import fileinput

## Dependences
from .pipeline_merger import merge_pipeline

import logging

class PipelineConfig(object):
    """Manage the configuration of a pipeline, deal with the read/write operation"""

    def __init__(self, default=None, data=None):

        if default:
            self.p_config = copy.deepcopy(default.p_config)
            self.p_tools = copy.deepcopy(default.p_tools)
        else:
            self.p_config = {
                # Basic configuration
                "team": "",
                "name": "",
                "config_file": "",
                "vars_files": [],
                "vars": {},
            }

            self.p_tools = {
                # Advanced Configuration
                "template": "",
                "merge": [],
                "partials": [],
                "cli": ""
            }
        
        if data:
            self.p_config = self.read_pipeline_config(data)

    ## Main processing function
    def read_pipeline_config(self, data):
        """
        Create the PipelineCongig Object for the space.
        Valid entries: -t,-p,-c,-l,-v
        Valid function: -tpl, -m, -s
        """

        logging.info("Reading the config")
        logging.debug(data)
        ## Fly cli args
        # Single arguements allowed
        self.p_config["team"]         = self.get_parameter(data, "-t", "team")
        self.p_config["name"]         = self.get_parameter(data, "-p", "pipeline", "name")
        self.p_config["config_file"]  = self.get_parameter(data, "-c", "config", "config_file")
        # Multiple arguments allowed
        self.p_config["vars_files"]   = self.get_list_of_paramters(data, "-l", "load-vars-from", "vars_files")

        # Get user vars
        self.p_config["vars"]         = self.get_list_of_paramters(data, "-v", "var", "vars")

        ##  Advanced args
        self.p_tools["template"]      = self.get_parameter(data, "-tpl", "template")
        self.p_tools["merge"]         = self.get_list_of_paramters(data, "-m", "merge")
        self.p_tools["partials"]      = self.get_list_of_paramters(data, "-s", "partials")

        return self.p_config
    
    ## Utils processing / transformations
    def process_to_be_merged(self, out_directory="./"):
        """Loop over the merge array and merge together file in order"""
        logging.info("Merging option")

        with open(self.p_config["config_file"]) as fp:
            m_source = yaml.safe_load(fp)

        # loop for the merge
        for  m in self.p_tools["merge"]:
            logging.info("merging: " + str(m))
            with open(m) as fp:
                m_destination = yaml.safe_load(fp)
 
            m_source = merge_pipeline(m_source, m_destination)

        out_merged = out_directory +'/config_files/' + self.p_config["name"] + ".yml"

        if not os.path.exists(out_directory + "/config_files/"):
            os.mkdir(out_directory + "/config_files/")
        
        with open(out_merged, 'w+') as fp:
            yaml.dump(m_source, fp, default_flow_style=False)


        self.p_config["config_file"] = out_merged

        return out_merged

    def process_partials(self):

        for p in reversed(self.p_tools["partials"][1:]):
            if isinstance(p, dict):
                # partials:
                # - { config_file: "config_file", with: {}}
                config_to_merge = self.p_config["config_file"] + p["config_file"] + ".yml"
                config_to_merge = self.replace_config_with(config_to_merge, p["with"])
            else:
                # partials:
                # - "config_file"
                config_to_merge = self.p_config["config_file"] + p + ".yml"
            self.p_tools["merge"].insert(0, config_to_merge)

        if isinstance(self.p_tools["partials"][0], dict):
            self.p_config["config_file"] = self.p_config["config_file"] + self.p_tools["partials"][0]["config_file"] + ".yml"
            self.p_config["config_file"] = self.replace_config_with(self.p_config["config_file"], self.p_tools["partials"][0]["with"])
        else:
            self.p_config["config_file"] = self.p_config["config_file"] + self.p_tools["partials"][0] + ".yml"

    def process_cli(self, out_directory="./"):
        """provide the fly cli for a given pipeline"""

        fly = "fly -t " + self.p_config["team"] + " set-pipeline" \
                                + " -p " + self.p_config["name"] \
                                + " -c "  + self.p_config["config_file"] \
                                + " ".join([" -l "  + l for l in self.p_config["vars_files"]]) \
                                + " ".join([" --var " + k + "=" + str(v) for k,v in self.flatten(self.p_config["vars"]).items()])

        self.p_tools["cli"] = fly

        out_directory = out_directory + '/fly_cli/'

        if not os.path.exists(out_directory):
            os.mkdir(out_directory)

        # Write output
        with open(out_directory + self.p_config["name"] + ".cmd", 'w+') as outfile:
            outfile.write("cd /d %~dp0")
            outfile.write('\n')
            outfile.write('cd ..')
            outfile.write('\n')
            outfile.write(fly)
            outfile.write('\n')
            outfile.write("pause")

        return fly

    # change the config object
    def set(self, key, value):
        self.p_config[key] = value

    ## Utils extract params
    def get(self, key):
        z = {**self.p_config, **self.p_tools}
        return z[key]

    def get_parameter(self, data, flag, name, alias=None):
        """
        Extract a string by flag or name or return default
        """

        if alias is None: alias = name

        if flag in data:
            r = data[flag]
        elif  name in data:
            r = data[name]
        else:
            r = self.get(alias)
        
        return r

    def get_list_of_paramters(self, data, flag, name, alias=None):
        """
        Extract a list by flag or name, concat with defaul value
        """
        if alias is None: alias = name
        r = self.get(alias)

        if flag in data:
            _r = data[flag] if not isinstance(data[flag], str) else [data[flag]]
        elif name in data:
            _r = data[name] if not isinstance(data[name], str) else [data[name]]
        else:
            _r = None

        if _r is not None:
            if isinstance(r, dict):
                r = {**r, **_r}
            else:
                r = r + _r
            
        return r

    # flatten is used for vars. We need to flatten then to create a valide cli
    def flatten(self, d, parent_key='', sep='.'):
        items = []
        for k, v in d.items():
            new_key = parent_key + sep + k if parent_key else k
            try:
                items.extend(self.flatten(v, new_key, sep=sep).items())
            except:
                items.append((new_key, v))
        return dict(items)

    # merge operation ca require temporary copy not to change the original file
    def create_temporary_copy(self, path):
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, 'temp_file_name')
        shutil.copy2(path, temp_path)
        return temp_path

    # do inplace replace in a configfile
    def replace_config_with(self, config_file, to_replace={}):

        config_file = self.create_temporary_copy(config_file)
        with fileinput.FileInput(config_file, inplace=True) as file:
            for line in file:
                for text_to_search, replacement_text in to_replace.items():
                    print(line.replace("((" + text_to_search + "))", replacement_text), end='')

        return config_file