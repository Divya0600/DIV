import os,sys,re

coliationpath = 'C:\\"Program Files (x86)"\\Coalition\\'
logspath = '//172.11.0.10/rotorenderlogs/logs/nuke' 

class Nuke_Renderer_Class(object):
    def _init_(self,*args):
        pass
    
    def GoAheadForRender(self,mainfilepath,framerange,host,bs,executablepath,jobtitle,affinity,*args):
        self.mainpath =  mainfilepath
        self.framerangeparts = framerange.split('-')
        self.host = host
        self.bs = int(bs)
        self.startframe=int(self.framerangeparts[0])
        self.endframe=int(self.framerangeparts[1])
        self.executablepath = executablepath
        filename = os.path.basename(self.mainpath)
        self.affinity = str(affinity)
        self.launchdummy(filename,self.host)
        self.readid()
        self.jobtitle = jobtitle
        count=0
        while self.endframe>=self.startframe:
            self.batch=self.startframe+self.bs-1
            if self.batch>=self.endframe:
                self.batch=self.endframe
            self.mkcd(filename,self.startframe,self.batch,self.id,self.host)
            self.startframe=self.startframe+self.bs
        
    def launchdummy(self,filename,host,*args):
        filename=filename[:-3]
        if self.affinity=='None':
            mkfulcmds= coliationpath+'control.exe -t "'+ filename +'" -c "echo" '+host+' add > "'+logspath.replace('/','\\')+'idno.txt"'
        else:
            mkfulcmds = coliationpath+'control.exe -t "'+ filename +'" -a "'+self.affinity+'" -c "echo" '+host+' add > "'+logspath.replace('/','\\')+'idno.txt"'

        os.system(mkfulcmds)

    def readid(self,*args):
        self.id = ""
        submit=open(logspath+'idno.txt', 'r')
        self.id=submit.read()
        submit.close            

    def mkcd(self,filename,startframe,batch,id,host,*args):
        startframe=str(startframe)
        endframe=str(batch)
        eid=re.split('\W+', id)
        eid=eid[0]
        mkcmd='"'+self.executablepath+'" -i -f -x -m 3 -F '+str(startframe)+'-'+str(endframe)+' -m 14 -V -- "'+self.mainpath+'"'

        batfile=logspath+'cmds/'+filename[:-3]+"_"+str(batch)+".cmd"

        if not os.path.isdir(logspath+'cmds/'):
            os.makedirs(logspath+'cmds/')

        sub_write=open(batfile,'w')
        sub_write.write(mkcmd)
        sub_write.close()
        mkfulcmd= coliationpath+'control -t "frames '+ startframe + '-' + endframe +'" -c "'+ batfile +'" -P '+ eid +' '+host+' add >> "'+logspath+'launchids.txt"'
        if self.affinity=='None':
            mkfulcmd= coliationpath+'control -t "frames '+ startframe + '-' + endframe +'" -c "'+ batfile +'" -P '+ eid +' '+host+' add >> "'+logspath+'launchids.txt"'
        else:
            mkfulcmd= coliationpath+'control -t "frames '+ startframe + '-' + endframe +'" -a "'+self.affinity+'" -c "'+ batfile +'" -P '+ eid +' '+host+' add >> "'+logspath+'launchids.txt"'
        os.system(mkfulcmd)
