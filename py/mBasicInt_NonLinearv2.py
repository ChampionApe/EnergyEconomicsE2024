from base import *
from nlModels import *
from scipy.stats import norm
from scipy.optimize import fsolve, minimize

class WritePropertyError(Exception):
    pass

class mSimpleNL(modelShellNL): 
	def __init__(self, db):
		mSimpleNL.updateDB(db)
		super().__init__(db,**kwargs)
		self.endo_vars = {'endo_var':['p'],'theta_var':[]}
		self.idx_endo = {'p': range(0,len(self.db['h']))} 		
		self.set_model_structure()
		self.set_model_parameters()

###########################################
# Initialize class
###########################################

	@staticmethod
	def updateDB(db):
		""" Function for initializing model database """
		db.updateAlias(alias = [('h','h_alias')])
		db.__setitem__('sigma',2); 						# Here we include a smoothing parameter as a scalar, but this could also be a scalar.
		db['p'] = pd.Series(0,index=db['h'],name='p')		# Here we initialize the price vector

	def set_model_parameters(self):
		""" This is a function loading in multiple read(-write) model properties (i.e. parameters) """
		self._hourlyGeneratingCapacity = (adjMultiIndex.bc(self.db['GeneratingCapacity'], self.db['id2hvt']) * self.db['CapVariation']).dropna().droplevel('hvt').astype(float)
		self._hourlyDemand_c = (self.db['LoadVariation'] * self.db['Load']).astype(float)
		self._Demand = self.hourlyDemand_c.groupby('h').sum()
		self._fuelCost = self.db['FuelPrice'].add(pyDbs.pdSum(self.db['EmissionIntensity'] * self.db['EmissionTax'], 'EmissionType'), fill_value=0).astype(float)
		self._averageMC = (pyDbs.pdSum((self.db['FuelMix'] * self.fuelCost).dropna(), 'BFt') + self.db['OtherMC']).astype(float)
	
	def set_model_structure(self):
		""" This is a function loading in multiple read model properties """
		self._H = len(self.db['h'])
		self._id2h = (adjMultiIndex.bc(self.db['GeneratingCapacity'], self.db['id2hvt']) * self.db['CapVariation']).dropna().droplevel('hvt').index

		
###########################################
# Set the parameters of the model 
# independent of the market equilibrium
###########################################

	@property
	def hourlyGeneratingCapacity(self):
		""" Hourly generating capacity measured in GJ """
		return self._hourlyGeneratingCapacity

	@hourlyGeneratingCapacity.setter
	def hourlyGeneratingCapacity(self,series):
		self._hourlyGeneratingCapacity = series
		self._id2h = series.index
	
	@property
	def hourlyDemand_c(self):
		""" Hourly demand measured in GJ """
		return self._hourlyDemand_c

	@hourlyDemand_c.setter
	def hourlyDemand_c(self,value):
		self._hourlyDemand_c = series

	@property
	def Demand(self):
		""" Hourly demand measured in GJ """
		return self._Demand

	@Demand.setter
	def Demand(self,value):
		raise WritePropertyError('Demand is read-only and given by hourlyDemand_c.')

	@property
	def fuelCost(self):
		""" Marginal fuel costs in €/GJ """
		return self._fuelCost

	@fuelCost.setter
	def fuelCost(self,series):
		self._fuelCost = series

	@property
	def averageMC(self):
		""" Marginal costs in €/GJ """
		return self._averageMC

	@averageMC.setter
	def averageMC(self,series):
		self._averageMC = series


###########################################
# Set the indices of the model, 
# determined by the data
###########################################

	@property 
	def H(self):
		return self._H

	@H.setter
	def H(self,multiindex):
		raise WritePropertyError('The number of hours (H) is read-only and determined by the data.')

	@property
	def id2h(self):
		return self._id2h

	@id2h.setter
	def id2h(self,series):
		raise WritePropertyError('The mapping between id and h is always given by the hourly generating capacity.')

###########################################
# Function for updating variables post
# simulations
###########################################

	def unloadSolutionToDB(self,roots):
		""" Returns af pandas series of x_vars in model database, when model is solved """
		[self.db.__setitem__(i,pd.Series(roots[self.idx_endo[i]],index=self.db[i].index,name=i)) for i in self.idx_endo.keys() if i in self.endo_vars['x_vars']];

	def postSolve(self):
		""" Define some variables to be saved post solution to the model. """
		self.db['hourlyGeneration'] = self.HourlyGeneration(self.x)


###########################################
# Function for changing endogenous numpy 
# array to pandas series
###########################################

	def xArray2pdSeries(self,x,variable='p'):
		""" Method for transforming endogenous variables from a numpy array to an indexed Pandas Series """
		return pd.Series(x[self.idx_endo[variable]],index=self.db[variable].index,name=variable) if variable in self.idx_endo.keys() else self.db[variable]

###########################################
# Model equations
###########################################	

	def Supply(self,x):
		""" Optimal capacity utilization """
		Inner = pd.Series(0,index=self.id2h).add(self.xArray2pdSeries(x,variable='p')).sub(self.averageMC).div(self.db['sigma'])
		CapacityUtilization = Inner.apply(norm.cdf)
		return (self.hourlyGeneratingCapacity * CapacityUtilization).groupby('h').sum()

	def ExcessDemand(self,x):
		""" Equilibrium definition defined as excess demand"""
		return self.Demand - self.Supply(x)


###########################################
# Define solver
###########################################



	# def Solve(self,x0=None,solver='scipy',analyticalJacobian=False,n_iter=None,update_db=True):
	# 	""" Function for finding equilibrium prices using the excess demand function """
	# 	# Check an equilibrium always exists:
	# 	if (pyDbs.pdSum(self.db['LoadVariation'] * self.db['Load'],'c')-pyDbs.pdSum(self.hourlyGeneratingCapacity,'id')>0).any():
	# 	 	warnings.warn(r'You are missing '+str((pyDbs.pdSum(self.db['LoadVariation'] * self.db['Load'],'c')-pyDbs.pdSum(self.hourlyGeneratingCapacity,'id')).round(1).max())+'in generating capacity for an equilibrium to exist', UserErrorMessage)
	# 	# Update parameters:
	# 	self.x = x0.copy()
	# 	n_iter = 100*(len(x0)+1) if n_iter is None else n_iter
	# 	# Now solve for the equilibrium:
	# 	if solver=='scipy':
	# 		fprime = self.Jacobian_of_ExcessDemand if analyticalJacobian else None
	# 		roots = fsolve(lambda x: self.NonLinearSystem(x), x0=x0, fprime=fprime, maxfev = n_iter)
	# 	elif solver=='manual':
	# 		roots =  self.manualSolver(x0=x0,n_iter=n_iter)
	# 	else:
	# 		warnings.warn(r'Currently, it is only possible to choose [scipy] or a [manual](ly) defined solver.', UserErrorMessage)
	# 	if np.isclose(self.NonLinearSystem(roots),b=0).all():
	# 		self.x = roots
	# 		self.unloadSolutionToDB(roots)
	# 		if update_db:
	# 			self.postSolve()
	# 	else:
	# 		warnings.warn(r'Solver did not find an equilibrium.', UserErrorMessage)
